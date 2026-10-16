"""Download-only cloud rehearsal. Never uploads or runs signal/order processing."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

from dotenv import load_dotenv

from scripts.run_v12_forward_automation import _cloud_configuration, fetch_exact_raw_closes, pending_valuation_dates
from src.config import get_secret
from src.forward_state_cloud import download_forward_state
from src.paper_ledger import AppendOnlyLedger
from src.forward_valuation import record_daily_valuations
from src.forward_dividends import load_reviews, assert_reviewed_history
from src.dashboard_read_model import build_dashboard_snapshot
from src.trading_calendar import NEW_YORK, previous_session, session_close


def main():
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / '.env')
    config = _cloud_configuration()
    now = datetime.now(timezone.utc)
    day = now.astimezone(NEW_YORK).date()
    if now < session_close(day):
        day = previous_session(day)
    with tempfile.TemporaryDirectory(prefix='v12-dividend-rehearsal-') as temporary:
        sandbox = Path(temporary)
        download_forward_state(sandbox, config['project_url'], config['api_key'], config['secret'],
            bucket=config['bucket'], object_path=get_secret('V12_FORWARD_STATE_SUPABASE_OBJECT') or 'forward_state/v12_forward_state.json')
        ledger = AppendOnlyLedger(sandbox / 'paper_ledger/v12_events.sqlite3')
        before = ledger.events()
        assert_reviewed_history(before, load_reviews(now))
        days = pending_valuation_dates(ledger, day.isoformat())
        for date in days:
            observations = {}
            def fetch(tickers, target):
                observations.update(fetch_exact_raw_closes(tickers, target))
                return observations
            record_daily_valuations(ledger, valuation_date=date, observation_fetcher=fetch, recorded_at=now)
            checkpoint = ledger.events()
            record_daily_valuations(ledger, valuation_date=date, observation_fetcher=lambda ts, d: observations, recorded_at=now)
            if ledger.events() != checkpoint:
                raise AssertionError('Rehearsal retry changed journal')
        after = ledger.events()
        if after[:len(before)] != before:
            raise AssertionError('Rehearsal changed original events')
        ledger.verify_integrity()
        added = after[len(before):]
        if any(r['event_type'] in {'FILL', 'ORDER', 'SIGNAL'} for r in added):
            raise AssertionError('Rehearsal unexpectedly changed trades')
        state = build_dashboard_snapshot(ledger.path)
        print(json.dumps({'mode':'ISOLATED_REHEARSAL_NO_CLOUD_WRITES', 'original_events':len(before),
            'added_events':len(added), 'recovered_dates':days, 'latest_valuation_date':state['latest_valuation_date'],
            'dividends_receivable':state.get('dividends_receivable'), 'cash':state['cash'],
            'entitlements':[{'portfolio':r['portfolio_id'],'ticker':r['ticker'],'shares':r['payload']['eligible_shares'],
                             'amount':r['payload']['amount'],'pay_date':r['payload']['pay_date']} for r in added if r['event_type']=='DIVIDEND_ENTITLEMENT'],
            'payments':sum(r['event_type']=='DIVIDEND_PAYMENT' for r in added),
            'original_hash_chain_preserved':True,'retry_unchanged':True},indent=2))


if __name__ == '__main__':
    main()
