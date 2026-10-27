"""Synthetic unsecured instalment lending. Run from any directory; no private data."""
from __future__ import annotations
import argparse
import calendar
import csv
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
START = date(2024, 1, 1)
ORIGINATION_END = date(2025, 6, 30)
OBSERVATION_END = date(2026, 6, 30)
SEED = 27102026
TABLES = ['borrowers','applications','income_observations','loans','repayment_schedule',
          'payments','payment_allocations','loan_snapshots','loan_age_outcomes',
          'collection_assignments','loan_costs','principal_events','simulation_truth']


def months(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def month_ends(start, end):
    d = start.replace(day=1)
    while d <= end:
        e = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        if start <= e <= end:
            yield e
        d = months(d, 1)


def split_amount(amount, n):
    q, r = divmod(amount, n)
    return [q + (i < r) for i in range(n)]


def simulate(loan_id, borrower, issued, principal, term, rate, risk, stress, rng, can_assign):
    principal_parts = split_amount(principal, term)
    interest_parts = split_amount(round(principal * rate * term), term)
    schedule = [{'id':f'{loan_id}-S{i+1}', 'due':months(issued,i+1), 'p':p,'i':interest_parts[i]}
                for i,p in enumerate(principal_parts)]
    # Payment paths depend on observable risk and cohort stress, plus random shocks.
    p_default = float(np.clip((0.025 + 0.34 * risk**2) * stress, .015, .65))
    p_late = float(np.clip(.10 + .30 * risk, .10, .40))
    u = rng.random()
    path = 'default_path' if u < p_default else ('late_path' if u < p_default+p_late else 'on_time')
    failed_from = int(rng.integers(0,term)) if path == 'default_path' else term
    plans = []
    for j,s in enumerate(schedule):
        if j >= failed_from:
            continue
        delay = int(rng.integers(8,76)) if path == 'late_path' and rng.random()<.72 else int(rng.integers(0,4))
        plans.append([s['due']+timedelta(days=delay),s['p']+s['i']])
    if path == 'default_path':
        overdue = schedule[failed_from]['due']
        remaining = sum(s['p']+s['i'] for s in schedule[failed_from:])
        recovery = round(remaining * float(rng.beta(1.1,4.5)))
        for k,amt in enumerate(split_amount(recovery,3)):
            if amt:
                plans.append([overdue+timedelta(days=120+k*65+int(rng.integers(1,25))),amt])
    # First 7-DPD episode is determined from information available at that date.
    assignment_date = None
    if can_assign:
        for s in schedule:
            candidate = s['due']+timedelta(days=7)
            owed = sum(x['p']+x['i'] for x in schedule if x['due']<=candidate)
            received = sum(a for d,a in plans if d<=candidate)
            if received < owed:
                assignment_date = candidate
                break
    arm = None
    if assignment_date:
        arm = 'treatment' if rng.random()<.5 else 'control'
        # A treatment can prompt a catch-up payment; future scheduled obligations persist.
        if arm == 'treatment' and rng.random()<.12:
            cure_date = assignment_date+timedelta(days=int(rng.integers(2,13)))
            owed = sum(x['p']+x['i'] for x in schedule if x['due']<=cure_date)
            received = sum(a for d,a in plans if d<=cure_date)
            extra = max(0,owed-received)
            if extra:
                plans.append([cure_date,extra])
    plans.sort(key=lambda x:x[0])
    # Allocate actual cash to the oldest instalment: principal, then its interest.
    paid_p = [0]*term
    paid_i = [0]*term
    allocations = []
    raw_payments = []
    for when,amount in plans:
        if when>OBSERVATION_END:
            continue
        left=amount
        rows=[]
        for j,s in enumerate(schedule):
            pp=min(left,s['p']-paid_p[j]);paid_p[j]+=pp;left-=pp
            ii=min(left,s['i']-paid_i[j]);paid_i[j]+=ii;left-=ii
            if pp+ii:
                rows.append((j,pp,ii))
        if rows:
            pid=f'{loan_id}-P{len(raw_payments)+1}'
            raw_payments.append({'id':pid,'date':when,'p':sum(r[1] for r in rows),'i':sum(r[2] for r in rows)})
            allocations.extend((pid,j,pp,ii,when) for j,pp,ii in rows)
    by_day=defaultdict(list)
    for pid,j,pp,ii,when in allocations:
        by_day[when].append((j,pp,ii))
    current_p=[0]*term;current_i=[0]*term
    snapshots=[];age_outcomes=[];default_date=None;writeoff_date=None;ead=None;written=0;payoff=None
    ever_30=False;max_dpd=0;assignment=None;dpd_on={};principal_on={}
    end_dates=set(month_ends(issued,OBSERVATION_END))
    anniversary={months(issued,n):n for n in range(0,7)}
    horizon=min(OBSERVATION_END,months(issued,term)+timedelta(days=330))
    when=issued
    while when<=horizon:
        for j,pp,ii in by_day.get(when,[]):
            current_p[j]+=pp;current_i[j]+=ii
        unpaid=[s['due'] for j,s in enumerate(schedule) if s['due']<=when and s['p']+s['i']>current_p[j]+current_i[j]]
        dpd=max(0,(when-min(unpaid)).days) if unpaid else 0
        cash_principal=principal-sum(current_p)
        max_dpd=max(max_dpd,dpd);ever_30|=dpd>=30
        if dpd>=90 and default_date is None:
            default_date=when;ead=cash_principal
        if dpd>=120 and cash_principal>0 and writeoff_date is None:
            writeoff_date=when;written=cash_principal
        if sum(current_p)+sum(current_i)==sum(s['p']+s['i'] for s in schedule) and payoff is None:
            payoff=when
        state='written_off' if writeoff_date else ('paid_off' if cash_principal==0 else ('current' if dpd==0 else '1-29' if dpd<30 else '30-59' if dpd<60 else '60-89' if dpd<90 else '90+'))
        outstanding=0 if writeoff_date else cash_principal
        if when in end_dates:
            snapshots.append((loan_id,when.isoformat(),outstanding,dpd,state,int(ever_30)))
        if when in anniversary:
            age_outcomes.append((loan_id,anniversary[when],when.isoformat(),int(ever_30),int(default_date is not None)))
        if assignment_date and when==assignment_date:
            assignment={'date':when,'arm':arm,'opening':outstanding}
        if assignment_date and when==assignment_date+timedelta(days=14):
            assignment['cured']=int(dpd==0 or payoff is not None)
        dpd_on[when]=dpd;principal_on[when]=cash_principal
        when+=timedelta(days=1)
    # Persist terminal states to the observation end without scanning every day.
    if horizon<OBSERVATION_END:
        for when in month_ends(horizon+timedelta(days=1),OBSERVATION_END):
            snapshots.append((loan_id,when.isoformat(),0 if writeoff_date else cash_principal,0 if payoff else (when-min(unpaid)).days if unpaid else 0,state,int(ever_30)))
    if assignment:
        end=assignment_date+timedelta(days=14)
        assignment['recovered']=sum(p['p'] for p in raw_payments if assignment_date<p['date']<=end)
        assignment['complete']=int(end<=OBSERVATION_END)
    # Snapshot history is sufficient to calculate lagged outcomes; applications use cash events as of their own date.
    return {'schedule':schedule,'payments':raw_payments,'allocations':allocations,'snapshots':snapshots,'age':age_outcomes,
            'default':default_date,'ead':ead,'writeoff':writeoff_date,'written':written,'payoff':payoff,
            'assignment':assignment,'path':path,'max_dpd':max_dpd,'last_due':schedule[-1]['due']}


def generate(n=50000, seed=SEED, output=None):
    rng=np.random.default_rng(seed)
    out=Path(output) if output else ROOT/'data';out.mkdir(parents=True,exist_ok=True)
    db=out/'credit.sqlite';db.unlink(missing_ok=True)
    con=sqlite3.connect(':memory:')
    con.executescript((ROOT/'sql/schema.sql').read_text())
    rows={t:[] for t in TABLES};profiles=[];history=defaultdict(list);assigned_borrowers=set()
    dates=sorted(START+timedelta(days=int(x)) for x in rng.integers(0,(ORIGINATION_END-START).days+1,n))
    for index,applied in enumerate(dates):
        if not profiles or rng.random()<.64:
            bid=f'SYN-B{len(profiles)+1:06d}'
            itype='salary' if rng.random()<.66 else 'self_employed'
            income=int(np.clip(rng.lognormal(math.log(220000),.60),65000,1800000))*100
            profile={'id':bid,'type':itype,'income':income,'risk':float(rng.beta(2.0,3.8)),
                     'cost_share':float(rng.uniform(.35,.67))}
            profiles.append(profile);rows['borrowers'].append((bid,itype,applied.isoformat()))
        else:
            profile=profiles[int(rng.integers(len(profiles)))];bid=profile['id']
        aid=f'SYN-A{index+1:06d}'
        prior=[h for h in history[bid] if h['issued']<=applied]
        prior_n=len(prior)
        # No future performance enters credit decisions.
        active=any(not h['result']['payoff'] or h['result']['payoff']>applied for h in prior)
        past_default=any(h['result']['default'] and h['result']['default']<=applied for h in prior)
        volatility=.07 if profile['type']=='salary' else .22
        verification_missing=rng.random()<.025
        incomes=[round(profile['income']*float(np.clip(rng.normal(1,volatility),.4,1.8))) for _ in range(3)]
        verified=None if verification_missing else int(np.median(incomes))
        if verified is not None:
            for k,val in enumerate(incomes):
                rows['income_observations'].append((aid,months(applied.replace(day=1),-3+k).isoformat(),val))
        essential=round(profile['income']*profile['cost_share'])
        debt=round(profile['income']*float(rng.uniform(0,.20)))
        requested=int(rng.choice([30000,50000,75000,100000,125000,150000,180000,200000]))*100
        term=int(rng.choice([1,2,3],p=[.12,.25,.63]))
        repeat='repeat' if prior_n else 'first_loan'
        score=int(np.clip(round(740-profile['risk']*235+rng.normal(0,28)+(12 if prior_n and not active else 0)),300,850))
        loose=date(2024,10,1)<=applied<=date(2024,12,31)
        cutoff=610 if loose else 640
        policy='expansion_2024q4' if loose else 'baseline_v1'
        rate=.03
        cap=15000000 if score>=700 else 12000000 if score>=660 else 9000000
        if verified is None:
            affordable=None
        else:
            max_payment=max(0,min(round(.25*verified)-debt,verified-essential-debt-3000000))
            affordable=int(max_payment*term/(1+rate*term))
            affordable=(affordable//100000)*100000
        amount=min(requested,15000000,cap,affordable or 0)
        if past_default: decision,reason='declined','prior_default'
        elif active: decision,reason='declined','existing_open_loan'
        elif verified is None: decision,reason='review','income_evidence_missing'
        elif amount<1000000: decision,reason='declined','affordability'
        elif score<cutoff: decision,reason='declined','score_cutoff'
        else: decision,reason='approved','policy_pass'
        accepted=int(decision=='approved' and rng.random()<.90)
        rows['applications'].append((aid,bid,applied.isoformat(),verified,essential,debt,requested,term,score,prior_n,repeat,policy,cutoff,cap,affordable,amount if decision=='approved' else 0,decision,reason,accepted))
        if not accepted or rng.random()<.025:
            continue
        lid=f'SYN-L{len(rows["loans"])+1:06d}'
        # Same-day funding avoids a future application observing a loan not yet disbursed.
        issued=applied
        stress=1.45 if date(2024,10,1)<=issued<=date(2025,2,28) else 1.0
        result=simulate(lid,bid,issued,amount,term,rate,profile['risk'],stress,rng,bid not in assigned_borrowers)
        history[bid].append({'issued':issued,'result':result})
        iso=lambda d:d.isoformat() if d else None
        complete=int(result['default'] is not None and result['default']+timedelta(days=180)<=OBSERVATION_END)
        rows['loans'].append((lid,aid,iso(issued),amount,term,rate,iso(result['last_due']),iso(result['default']),result['ead'],iso(result['writeoff']),result['written'],iso(result['payoff']),complete))
        for j,s in enumerate(result['schedule']):
            rows['repayment_schedule'].append((s['id'],lid,j+1,iso(s['due']),s['p'],s['i']))
        events=[(lid,iso(issued),'disbursement',amount)]
        for p in result['payments']:
            post=int(result['writeoff'] is not None and p['date']>result['writeoff'])
            rows['payments'].append((p['id'],lid,iso(p['date']),p['p'],p['i'],post))
            if not post:
                events.append((lid,iso(p['date']),'principal_repayment',-p['p']))
        for pid,j,pp,ii,when in result['allocations']:
            rows['payment_allocations'].append((pid,result['schedule'][j]['id'],pp,ii))
        if result['writeoff']:
            events.append((lid,iso(result['writeoff']),'writeoff',-result['written']))
        rows['principal_events'].extend(events)
        terminal_seen=False
        for snapshot in result['snapshots']:
            terminal=snapshot[4] in ('paid_off','written_off')
            if not terminal_seen:
                rows['loan_snapshots'].append(snapshot)
            terminal_seen |= terminal
        rows['loan_age_outcomes'].extend(result['age'])
        assignment=result['assignment']
        if assignment:
            assigned_borrowers.add(bid)
            cost=35000 if assignment['arm']=='treatment' else 15000
            rows['collection_assignments'].append((f'SYN-C{len(rows["collection_assignments"])+1:06d}',bid,lid,iso(assignment['date']),assignment['arm'],assignment['opening'],assignment['cured'],assignment['recovered'],cost,assignment['complete']))
            rows['loan_costs'].append((lid,iso(assignment['date']),'collections',cost))
        rows['loan_costs'].append((lid,iso(issued),'acquisition',150000 if prior_n==0 else 50000))
        for s in result['schedule']:
            rows['loan_costs'].append((lid,iso(s['due']),'servicing',20000))
        rows['simulation_truth'].append((lid,result['path'],stress,1))
        if (index+1)%10000==0:
            print(f'Processed {index+1:,} applications',flush=True)
    for t in TABLES:
        if rows[t]:
            con.executemany(f'INSERT INTO {t} VALUES ({",".join("?" for _ in rows[t][0])})',rows[t])
    con.commit()
    assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
    manifest={'seed':seed,'applications':n,'origination_start':str(START),'origination_end':str(ORIGINATION_END),
              'observation_end':str(OBSERVATION_END),'default_dashboard_date':str(ORIGINATION_END),'synthetic':True,'tables':{}}
    for t in TABLES:
        cur=con.execute(f'SELECT * FROM {t} ORDER BY rowid')
        target=out/f'{t}.csv'
        with target.open('w',newline='') as f:
            w=csv.writer(f);w.writerow([x[0] for x in cur.description]);w.writerows(cur)
        manifest['tables'][t]={'rows':len(rows[t]),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    con.execute('VACUUM');db.write_bytes(con.serialize());con.close()
    print(json.dumps({k:v['rows'] for k,v in manifest['tables'].items()},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--applications',type=int,default=50000);parser.add_argument('--seed',type=int,default=SEED);parser.add_argument('--output',type=Path)
    args=parser.parse_args();generate(args.applications,args.seed,args.output)
