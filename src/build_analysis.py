"""As-of analysis, temporal model evaluation and compact browser data."""
from __future__ import annotations
import calendar
import json
import math
import sqlite3
from datetime import date,timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import fisher_exact,binomtest
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score,brier_score_loss,log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parents[1]
ASOF='2025-06-30'
DATES=[f'2025-{m:02d}-{calendar.monthrange(2025,m)[1]}' for m in range(1,7)]
SEGMENTS=['all','first_loan','repeat']
con=sqlite3.connect(':memory:');con.deserialize((ROOT/'data/credit.sqlite').read_bytes())
apps=pd.read_sql_query('SELECT a.*,b.income_type FROM applications a JOIN borrowers b USING(borrower_id)',con)
loans=pd.read_sql_query('SELECT * FROM loans',con)
payments=pd.read_sql_query('SELECT * FROM payments',con)
snapshots=pd.read_sql_query('SELECT s.*,a.borrower_segment,a.risk_score,a.term_months FROM loan_snapshots s JOIN loans l USING(loan_id) JOIN applications a USING(application_id)',con)
age=pd.read_sql_query('SELECT o.*,substr(l.disbursed_date,1,7) AS vintage,a.borrower_segment FROM loan_age_outcomes o JOIN loans l USING(loan_id) JOIN applications a USING(application_id)',con)
costs=pd.read_sql_query('SELECT c.*,a.borrower_segment FROM loan_costs c JOIN loans l USING(loan_id) JOIN applications a USING(application_id)',con)
ledger=pd.read_sql_query('SELECT e.*,a.borrower_segment FROM principal_events e JOIN loans l USING(loan_id) JOIN applications a USING(application_id)',con)
loan_apps=loans.merge(apps,on='application_id',suffixes=('_loan',''))
payments=payments.merge(loan_apps[['loan_id','borrower_segment']],on='loan_id')

def filt(df,seg):
 return df if seg=='all' else df[df.borrower_segment==seg]
def ratio(n,d):
 return float(n/d) if d else None

def features(df,amount=None):
 income=df.verified_income_kobo.to_numpy(dtype=float)
 amount=df.principal_kobo.to_numpy(dtype=float) if amount is None else np.asarray(amount,dtype=float)
 term=df.term_months.to_numpy(dtype=float)
 burden=(df.existing_debt_kobo.to_numpy()+amount*(1+.03*term)/term)/income
 return np.column_stack([df.risk_score.to_numpy()/100,np.log(income/100),df.existing_debt_kobo.to_numpy()/income,
                         burden,term,(df.borrower_segment=='repeat').astype(int)])

# Labels require the whole maturity + 90 day outcome window to be observable.
loan_apps['horizon']=(pd.to_datetime(loan_apps.final_due_date)+pd.Timedelta(days=90)).dt.strftime('%Y-%m-%d')
loan_apps['label']=((loan_apps.default_date.notna())&(loan_apps.default_date<=loan_apps.horizon)).astype(int)
train=loan_apps[(loan_apps.disbursed_date<'2024-10-01')&(loan_apps.horizon<=ASOF)].copy()
test=loan_apps[(loan_apps.disbursed_date>='2024-10-01')&(loan_apps.disbursed_date<'2025-01-01')&(loan_apps.horizon<=ASOF)].copy()
model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=2000,C=.1,random_state=27102026))
model.fit(features(train),train.label)
prob=model.predict_proba(features(test))[:,1]
scaler=model[0];lr=model[1]
metrics={'training_loans':len(train),'test_loans':len(test),'training_end':'2024-09-30','test_end':'2024-12-31','outcomes_known_by':ASOF,
         'auc':roc_auc_score(test.label,prob),'brier':brier_score_loss(test.label,prob),'log_loss':log_loss(test.label,prob),
         'observed_default_rate':float(test.label.mean()),'predicted_default_rate':float(prob.mean()),
         'training_min_score':int(train.risk_score.min()),'test_min_score':int(test.risk_score.min()),'features':['score/100','log(monthly income naira)','existing debt / income','total repayment / income','term months','repeat borrower']}
calibration=[]
bin_codes=pd.qcut(prob,5,labels=False,duplicates='drop')
for b in np.unique(bin_codes):
 mask=bin_codes==b
 if mask.any():calibration.append({'predicted':float(prob[mask].mean()),'observed':float(test.label.to_numpy()[mask].mean()),'n':int(mask.sum())})
assert sum(row['n'] for row in calibration)==len(test)
metrics['calibration']=calibration

mature=loan_apps[loan_apps.default_date.notna()&((pd.to_datetime(loan_apps.default_date)+pd.Timedelta(days=180)).dt.strftime('%Y-%m-%d')<=ASOF)].copy()
recovered={}
for r in mature.itertuples():
 end=(date.fromisoformat(r.default_date)+timedelta(days=180)).isoformat()
 recovered[r.loan_id]=int(payments[(payments.loan_id==r.loan_id)&(payments.payment_date>r.default_date)&(payments.payment_date<=end)].principal_kobo.sum())
mature['recovered180']=mature.loan_id.map(recovered)
# Zero-EAD defaults cannot supply a principal LGD denominator.
mature=mature[mature.ead_kobo>0]
loss_params={}
for term in [1,2,3]:
 group=mature[mature.term_months==term]
 if len(group)<30: group=mature
 loss_params[str(term)]={'n':len(group),'ead_factor':float((group.ead_kobo/group.principal_kobo).mean()),
  'lgd':float((group.ead_kobo.sum()-group.recovered180.sum())/group.ead_kobo.sum())}
pre=apps[apps.application_date<'2025-04-01']
accepted=pre[pre.accepted==1]
funded=set(loans.application_id)
conversion=float(accepted.application_id.isin(funded).sum()/max(1,(pre.decision=='approved').sum()))

# Browser-side policy population is fixed; date selection only changes historical workspaces.
pop=apps[(apps.application_date>='2025-04-01')&(apps.application_date<=ASOF)].copy()
cols=['application_id','application_date','borrower_segment','risk_score','verified_income_kobo','essential_costs_kobo','existing_debt_kobo','requested_kobo','term_months','risk_cap_kobo','decision_reason']
records=[]
for r in pop[cols].itertuples(index=False,name=None):
 a,dt,sg,score,inc,ess,debt,req,term,cap,reason=r
 records.append([a,dt,sg,int(score),None if pd.isna(inc) else int(inc)/100,int(ess)/100,int(debt)/100,int(req)/100,int(term),int(cap)/100,reason in ['prior_default','existing_open_loan']])

# Collections curves and confidence intervals use intention-to-treat assignment.
assign=pd.read_sql_query('SELECT c.*,a.borrower_segment FROM collection_assignments c JOIN loans l USING(loan_id) JOIN applications a USING(application_id)',con)
schedules=pd.read_sql_query('SELECT * FROM repayment_schedule',con)
alloc=pd.read_sql_query('SELECT a.*,p.payment_date FROM payment_allocations a JOIN payments p USING(payment_id)',con)
sched_groups={k:v for k,v in schedules.groupby('loan_id')}
alloc_groups={k:v for k,v in alloc.groupby('schedule_id')}
cure_days={}
for a in assign.itertuples():
 first=None
 for day in range(15):
  dt=(date.fromisoformat(a.assignment_date)+timedelta(days=day)).isoformat();unpaid=False
  for s in sched_groups[a.loan_id].itertuples():
   if s.due_date>dt:continue
   ac=alloc_groups.get(s.schedule_id)
   paid=0 if ac is None else ac[ac.payment_date<=dt][['principal_kobo','interest_kobo']].to_numpy().sum()
   if paid<s.principal_due_kobo+s.interest_due_kobo:unpaid=True;break
  if not unpaid:first=day;break
 cure_days[a.assignment_id]=first
assign['cure_day']=assign.assignment_id.map(cure_days)

def wilson(k,n):
 if not n:return [None,None]
 p=k/n;z=1.95996398454;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
 return [mid-half,mid+half]

def experiment(group):
 arms=[]
 for arm in ['control','treatment']:
  g=group[group.arm==arm];n=len(g);k=int(g.cured_14d.sum())
  arms.append({'arm':arm,'n':n,'cured':k,'rate':ratio(k,n),'cost':int(g.cost_kobo.sum())/100,'recovered':int(g.recovered_principal_14d_kobo.sum())/100,
  'opening':int(g.opening_principal_kobo.sum())/100,'curve':[float((g.cure_day<=d).sum()/n) if n else None for d in range(15)]})
 c,t=arms
 if not c['n'] or not t['n']:return {'arms':arms,'uplift':None,'ci':[None,None],'p':None,'srm_p':None}
 diff=t['rate']-c['rate'];cl,cu=wilson(c['cured'],c['n']);tl,tu=wilson(t['cured'],t['n'])
 ci=[diff-math.sqrt((t['rate']-tl)**2+(cu-c['rate'])**2),diff+math.sqrt((tu-t['rate'])**2+(c['rate']-cl)**2)]
 return {'arms':arms,'uplift':diff,'ci':ci,'p':float(fisher_exact([[t['cured'],t['n']-t['cured']],[c['cured'],c['n']-c['cured']]]).pvalue),
  'srm_p':float(binomtest(t['n'],t['n']+c['n'],.5).pvalue),
  'net_per_borrower':t['recovered']/t['n']-c['recovered']/c['n']-(t['cost']/t['n']-c['cost']/c['n'])}

historical={}
for asof in DATES:
 historical[asof]={}
 month_start=asof[:7]+'-01'
 prior_end=(date.fromisoformat(month_start)-timedelta(days=1)).isoformat()
 for seg in SEGMENTS:
  ss=filt(snapshots,seg);ss=ss[ss.snapshot_date==asof]
  la=filt(loan_apps,seg);pp=filt(payments,seg);le=filt(ledger,seg);cc=filt(costs,seg)
  start=date.fromisoformat(month_start);end=date.fromisoformat(asof);days=(end-start).days+1
  balances=[];balance=int(le[le.event_date<month_start].amount_kobo.sum())
  events=le.groupby('event_date').amount_kobo.sum().to_dict()
  for d in range(days):balance+=int(events.get(str(start+timedelta(days=d)),0));balances.append(balance)
  average=float(np.mean(balances))/100
  writeoff=la[(la.writeoff_date>=month_start)&(la.writeoff_date<=asof)].written_off_kobo.sum()/100
  recovery=pp[(pp.is_post_writeoff==1)&(pp.payment_date>=month_start)&(pp.payment_date<=asof)].principal_kobo.sum()/100
  current_interest=pp[(pp.payment_date>=month_start)&(pp.payment_date<=asof)].interest_kobo.sum()/100
  current_cost=cc[(cc.cost_date>=month_start)&(cc.cost_date<=asof)].amount_kobo.sum()/100
  disb=la[(la.disbursed_date>=month_start)&(la.disbursed_date<=asof)].principal_kobo.sum()/100
  total=ss.outstanding_principal_kobo.sum()/100
  buckets=[]
  for state in ['current','1-29','30-59','60-89','90+']:
   value=ss[ss.state==state].outstanding_principal_kobo.sum()/100
   buckets.append({'name':state,'value':float(value),'share':ratio(value,total)})
  trend=[]
  for dt in sorted(snapshots.snapshot_date.unique()):
   if dt>asof:break
   s=filt(snapshots,seg);s=s[s.snapshot_date==dt]
   funded_month=la[la.disbursed_date.str.startswith(dt[:7])]
   trend.append({'date':dt,'balance':float(s.outstanding_principal_kobo.sum()/100),'disbursed':float(funded_month.principal_kobo.sum()/100)})
  segrows=[]
  for name in ['first_loan','repeat']:
   if seg!='all' and name!=seg:continue
   s=ss[ss.borrower_segment==name];bal=s.outstanding_principal_kobo.sum()/100
   segrows.append({'segment':name,'loans':int((s.outstanding_principal_kobo>0).sum()),'balance':float(bal),'dpd30':ratio(s[s.days_past_due>=30].outstanding_principal_kobo.sum()/100,bal)})
  ages=filt(age,seg);ages=ages[ages.anniversary_date<=asof]
  vint=[]
  for (v,m),g in ages.groupby(['vintage','month_on_book']):
   vint.append({'vintage':v,'mob':int(m),'n':len(g),'rate':float(g.ever_30_dpd.mean())})
  opening=filt(snapshots,seg);opening=opening[(opening.snapshot_date==prior_end)&(~opening.state.isin(['paid_off','written_off']))]
  ending=ss[['loan_id','state']].rename(columns={'state':'ending'})
  transitions=opening.merge(ending,on='loan_id',how='left')
  assert transitions.ending.notna().all()
  matrix=[]
  for st,g in transitions.groupby('state'):
   for target in ['current','1-29','30-59','60-89','90+','paid_off','written_off']:
    matrix.append({'from':st,'to':target,'n':int((g.ending==target).sum()),'denom':len(g),'rate':float((g.ending==target).mean())})
  ag=filt(assign,seg);ag=ag[(pd.to_datetime(ag.assignment_date)+pd.Timedelta(days=14)).dt.strftime('%Y-%m-%d')<=asof]
  exp=experiment(ag);exp['segments']={g:experiment(filt(ag,g)) for g in ['first_loan','repeat']}
  historical[asof][seg]={'balance':float(total),'active':int((ss.outstanding_principal_kobo>0).sum()),'disbursed':float(disb),
   'dpd30':ratio(ss[ss.days_past_due>=30].outstanding_principal_kobo.sum()/100,total),'annual_loss':ratio((writeoff-recovery)*365,average*days),
   'average_balance':average,'net_loss':float(writeoff-recovery),'interest':float(current_interest),'costs':float(current_cost),
   'funding_cost':average*.2*days/365,'contribution':float(current_interest-(writeoff-recovery)-current_cost-average*.2*days/365),
   'buckets':buckets,'trend':trend,'segments':segrows,'vintages':vint,'transitions':matrix,'experiment':exp}

payload={'meta':{'synthetic':True,'asof':ASOF,'dates':DATES,'population_start':'2025-04-01','population_end':ASOF,'population_months':3,
 'pricing_monthly_flat':.03,'max_loan':150000,'baseline_cutoff':640,'baseline_ceiling':.25,'baseline_funding':.20,'residual_floor':30000,
 'conversion':conversion,'feature_names':metrics['features']},'model':{'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coef':lr.coef_[0].tolist(),'intercept':float(lr.intercept_[0]),'metrics':metrics},
 'loss_parameters':loss_params,'population_columns':['id','date','segment','score','income','essential','debt','requested','term','riskcap','blocked'],
 'population':records,'historical':historical}
(ROOT/'assets').mkdir(exist_ok=True)
# JavaScript assignment permits offline opening and avoids a network fetch on GitHub Pages.
def clean(o):
 if isinstance(o,dict):return {k:clean(v) for k,v in o.items()}
 if isinstance(o,list):return [clean(v) for v in o]
 if isinstance(o,(np.integer,)):return int(o)
 if isinstance(o,(np.floating,float)):return None if not math.isfinite(o) else float(f'{float(o):.10g}')
 return o
payload=clean(payload)
(ROOT/'assets/analysis-data.js').write_text('window.CREDIT_DATA='+json.dumps(payload,separators=(',',':'))+';\n')
parity=[]
for row,pr in zip(test.head(25).itertuples(),prob[:25]):
 parity.append({'application':[row.application_id,row.application_date,row.borrower_segment,int(row.risk_score),row.verified_income_kobo/100,row.essential_costs_kobo/100,row.existing_debt_kobo/100,row.requested_kobo/100,int(row.term_months),row.risk_cap_kobo/100,False],'amount':row.principal_kobo/100,'pd':float(pr)})
(ROOT/'analysis/scoring-parity.json').write_text(json.dumps(clean(parity),indent=2)+'\n')
(ROOT/'analysis/model-report.json').write_text(json.dumps(clean({'model':metrics,'loss_parameters':loss_params,'acceptance_funding_conversion':conversion}),indent=2)+'\n')
(ROOT/'analysis/historical-summary.json').write_text(json.dumps(clean(historical[ASOF]['all']),indent=2)+'\n')
print(json.dumps({'model':clean(metrics),'loss_parameters':clean(loss_params),'policy_applications':len(records),'browser_data_kb':round((ROOT/'assets/analysis-data.js').stat().st_size/1024)},indent=2))
