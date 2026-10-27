"""Accounting identities, time boundaries, as-of outcomes and randomisation checks."""
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
con=sqlite3.connect(':memory:')
con.deserialize((ROOT/'data/credit.sqlite').read_bytes())
con.row_factory=sqlite3.Row
con.execute('CREATE INDEX IF NOT EXISTS allocations_schedule ON payment_allocations(schedule_id)')
con.execute('CREATE INDEX IF NOT EXISTS events_loan_date ON principal_events(loan_id,event_date)')
checks=[]

def check(name, actual, expected=0):
    checks.append({'check':name,'passed':actual==expected,'observed':actual,'expected':expected})

def count(sql):
    return con.execute(sql).fetchone()[0]

check('SQLite integrity',con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
check('Foreign key violations',len(con.execute('PRAGMA foreign_key_check').fetchall()))
check('Application count',count('SELECT count(*) FROM applications'),50000)
check('Income evidence median',count('''SELECT count(*) FROM applications a WHERE verified_income_kobo IS NOT NULL AND
 verified_income_kobo != (SELECT income_kobo FROM income_observations i WHERE i.application_id=a.application_id ORDER BY income_kobo LIMIT 1 OFFSET 1)'''))
check('Only prior complete income months',count('''SELECT count(*) FROM income_observations i JOIN applications a USING(application_id)
 WHERE i.income_month>=date(a.application_date,'start of month')'''))
check('Schedule principal equals disbursement',count('''SELECT count(*) FROM loans l WHERE principal_kobo!=(SELECT sum(principal_due_kobo) FROM repayment_schedule s WHERE s.loan_id=l.loan_id)'''))
check('Disbursement requires approval and acceptance',count('''SELECT count(*) FROM loans l JOIN applications a USING(application_id)
 WHERE decision!='approved' OR accepted!=1 OR l.principal_kobo!=a.assigned_kobo'''))
check('Approval affordability and amount caps',count('''SELECT count(*) FROM applications WHERE decision='approved' AND
 (assigned_kobo>requested_kobo OR assigned_kobo>risk_cap_kobo OR assigned_kobo>affordable_cap_kobo OR assigned_kobo>15000000 OR verified_income_kobo IS NULL)'''))
check('Repayment burden ceiling',count('''SELECT count(*) FROM loans l JOIN applications a USING(application_id) JOIN repayment_schedule s USING(loan_id)
 WHERE s.principal_due_kobo+s.interest_due_kobo+a.existing_debt_kobo>a.verified_income_kobo*.25+1'''))
check('Residual income floor',count('''SELECT count(*) FROM loans l JOIN applications a USING(application_id) JOIN repayment_schedule s USING(loan_id)
 WHERE a.verified_income_kobo-a.essential_costs_kobo-a.existing_debt_kobo-s.principal_due_kobo-s.interest_due_kobo<3000000-1'''))
check('Principal allocations reconcile to payments',count('''SELECT count(*) FROM payments p WHERE principal_kobo!=(SELECT sum(principal_kobo) FROM payment_allocations a WHERE a.payment_id=p.payment_id)'''))
check('Interest allocations reconcile to payments',count('''SELECT count(*) FROM payments p WHERE interest_kobo!=(SELECT sum(interest_kobo) FROM payment_allocations a WHERE a.payment_id=p.payment_id)'''))
check('No overallocated instalments',count('''SELECT count(*) FROM repayment_schedule s WHERE principal_due_kobo<coalesce((SELECT sum(principal_kobo) FROM payment_allocations a WHERE a.schedule_id=s.schedule_id),0)
 OR interest_due_kobo<coalesce((SELECT sum(interest_kobo) FROM payment_allocations a WHERE a.schedule_id=s.schedule_id),0)'''))
check('No pre-funding or future payments',count('''SELECT count(*) FROM payments p JOIN loans l USING(loan_id) WHERE p.payment_date<l.disbursed_date OR p.payment_date>'2026-06-30' '''))
check('No writeoff before default',count('''SELECT count(*) FROM loans WHERE writeoff_date IS NOT NULL AND (default_date IS NULL OR writeoff_date<default_date)'''))
check('No negative snapshot balances',count('SELECT count(*) FROM loan_snapshots WHERE outstanding_principal_kobo<0'))
check('Single experiment assignment per borrower',count('SELECT count(*)-count(DISTINCT borrower_id) FROM collection_assignments'))

# Independent reconstruction from cash allocations, not the generator state.
schedules=defaultdict(list)
for r in con.execute('SELECT * FROM repayment_schedule'):
    schedules[r['loan_id']].append(dict(r))
payments=defaultdict(list)
for r in con.execute('SELECT * FROM payments ORDER BY payment_date'):
    payments[r['loan_id']].append(dict(r))
allocations=defaultdict(list)
for r in con.execute('''SELECT a.*,p.payment_date FROM payment_allocations a JOIN payments p USING(payment_id)'''):
    allocations[r['schedule_id']].append(dict(r))
loans={r['loan_id']:dict(r) for r in con.execute('SELECT * FROM loans')}

def state(lid,asof):
    l=loans[lid]
    pp=sum(p['principal_kobo'] for p in payments[lid] if p['payment_date']<=asof)
    owed=[]
    for s in schedules[lid]:
        if s['due_date']>asof: continue
        paid=sum(a['principal_kobo']+a['interest_kobo'] for a in allocations[s['schedule_id']] if a['payment_date']<=asof)
        if paid<s['principal_due_kobo']+s['interest_due_kobo']: owed.append(s['due_date'])
    dpd=(date.fromisoformat(asof)-date.fromisoformat(min(owed))).days if owed else 0
    principal=0 if l['writeoff_date'] and l['writeoff_date']<=asof else l['principal_kobo']-pp
    return principal,dpd

balance_errors=dpd_errors=ead_errors=writeoff_errors=experiment_errors=0
for s in con.execute('SELECT * FROM loan_snapshots'):
    principal,dpd=state(s['loan_id'],s['snapshot_date'])
    balance_errors+=principal!=s['outstanding_principal_kobo']
    dpd_errors+=dpd!=s['days_past_due']
for l in loans.values():
    if l['default_date']:
        principal,dpd=state(l['loan_id'],l['default_date'])
        ead_errors+=principal!=l['ead_kobo'] or dpd!=90
    if l['writeoff_date']:
        remaining=l['principal_kobo']-sum(p['principal_kobo'] for p in payments[l['loan_id']] if p['payment_date']<=l['writeoff_date'])
        writeoff_errors+=remaining!=l['written_off_kobo']
for a in con.execute('SELECT * FROM collection_assignments'):
    end=(date.fromisoformat(a['assignment_date'])+timedelta(days=14)).isoformat()
    opening,dpd=state(a['loan_id'],a['assignment_date'])
    _,ending_dpd=state(a['loan_id'],end)
    recovered=sum(p['principal_kobo'] for p in payments[a['loan_id']] if a['assignment_date']<p['payment_date']<=end)
    experiment_errors+=int(opening!=a['opening_principal_kobo'] or dpd!=7 or int(ending_dpd==0)!=a['cured_14d'] or recovered!=a['recovered_principal_14d_kobo'])
check('Snapshot principal reconstructed from cash',balance_errors)
check('Snapshot DPD reconstructed from unpaid schedule',dpd_errors)
check('First default EAD and 90-DPD boundary',ead_errors)
check('Writeoff principal reconstructed from cash',writeoff_errors)
check('Experiment eligibility and 14-day outcomes',experiment_errors)
check('Principal ledger conservation',count('''SELECT count(*) FROM loans l WHERE
 (SELECT sum(amount_kobo) FROM principal_events e WHERE e.loan_id=l.loan_id)!=
 l.principal_kobo-coalesce((SELECT sum(principal_kobo) FROM payments p WHERE p.loan_id=l.loan_id AND p.is_post_writeoff=0),0)-l.written_off_kobo'''))
for view in ['monthly_applications','monthly_portfolio','monthly_loan_transitions','vintage_curves','collection_results','monthly_financials']:
    con.execute(f'DROP VIEW IF EXISTS {view}')
con.executescript((ROOT/'sql/reporting_views.sql').read_text())
check('Transition destinations resolved',count('SELECT count(*) FROM monthly_loan_transitions WHERE ending_state IS NULL'))
# Check the interval-weighted daily balance on a specific month against a day-by-day sum.
start=date(2025,6,1);end=date(2025,6,30)
events=defaultdict(int)
for e in con.execute('SELECT event_date,sum(amount_kobo) FROM principal_events GROUP BY event_date'):
    events[e[0]]=e[1]
balance=sum(v for d,v in events.items() if d<str(start));exposure=0
for n in range(30):
    day=str(start+timedelta(days=n));balance+=events[day];exposure+=balance
sql_average=con.execute("SELECT avg_daily_principal_kobo FROM monthly_financials WHERE month_start='2025-06-01'").fetchone()[0]
check('Average daily balance independently summed',abs(sql_average-exposure/30)<.01,True)
summary={
 'synthetic':True,'default_dashboard_date':'2025-06-30','followup_end':'2026-06-30',
 'counts':{t:count(f'SELECT count(*) FROM {t}') for t in ['borrowers','applications','loans','payments','loan_snapshots','collection_assignments']},
 'decisions':[dict(r) for r in con.execute('SELECT decision,count(*) AS applications FROM applications GROUP BY decision')],
 'portfolio_at_default_date':dict(con.execute("SELECT * FROM monthly_portfolio WHERE snapshot_date='2025-06-30'").fetchone()),
 'collections':[dict(r) for r in con.execute('SELECT * FROM collection_results')],
 'matured_defaults':count('SELECT count(*) FROM loans WHERE recovery_window_complete=1'),
 'checks':checks,'all_passed':all(c['passed'] for c in checks)
}
(ROOT/'checks/validation_report.json').write_text(json.dumps(summary,indent=2)+'\n')
# Save views into the portable database after successful execution.
con.commit();(ROOT/'data/credit.sqlite').write_bytes(con.serialize())
print(json.dumps(summary,indent=2))
sys.exit(0 if summary['all_passed'] else 1)
