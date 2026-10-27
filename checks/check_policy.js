const fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'..');const context={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'assets/analysis-data.js'),'utf8'),context);
const data=context.window.CREDIT_DATA;const P=require('../assets/policy-engine.js');
const loss=Math.round(100*data.model.metrics.observed_default_rate/data.model.metrics.predicted_default_rate)/100;
const config={cutoff:640,ceiling:.25,funding:.2,loss};const tests=[];
function check(name,passed){tests.push({check:name,passed:Boolean(passed)});}
const baseline=P.simulate(data,config);
check('Default and explicit baseline agree',P.simulate(data,{...config}).contribution===baseline.contribution);
const strict=P.simulate(data,{...config,cutoff:700});const loose=P.simulate(data,{...config,cutoff:620});
check('Stricter cut-off does not increase approvals',strict.approved<=baseline.approved);
check('Looser cut-off does not reduce approvals',loose.approved>=baseline.approved);
const lowerFunding=P.simulate(data,{...config,funding:.1});
check('Funding changes no underwriting decision',lowerFunding.approved===baseline.approved);
check('Lower funding cost raises contribution',lowerFunding.contribution>baseline.contribution);
const stress=P.simulate(data,{...config,loss:loss*1.5});
check('Loss stress leaves principal unchanged',stress.principal===baseline.principal);
check('Loss stress lowers contribution',stress.contribution<baseline.contribution);
check('Contribution bridge reconciles',Math.abs(baseline.revenue-baseline.expectedLoss-baseline.funding-baseline.acquisition-baseline.servicing-baseline.collections-baseline.contribution)<1e-6);
for(const segment of ['all','first_loan','repeat']){
 for(const cutoff of [580,620,640,700,740])for(const ceiling of [.15,.25,.4]){
  const s=P.simulate(data,{...config,cutoff,ceiling},segment);
  check(`Finite totals ${segment} / ${cutoff} / ${ceiling}`,['principal','expectedLoss','contribution','lossRate'].every(k=>Number.isFinite(s[k])));
  check(`Affordability caps ${segment} / ${cutoff} / ${ceiling}`,s.rows.filter(r=>r.pass).every(r=>r.amount<=150000&&r.amount<=r.request&&r.burden<=ceiling+1e-8&&r.income-r.essential-r.debt-r.amount*(1+.03*r.term)/r.term>=30000-1e-8));
 }
}
const summarize=s=>({cutoff:s.config.cutoff,ceiling:s.config.ceiling,approval:s.approval,approved:s.approved,principal:s.principal,expectedLoss:s.expectedLoss,lossRate:s.lossRate,revenue:s.revenue,funding:s.funding,acquisition:s.acquisition,servicing:s.servicing,collections:s.collections,contribution:s.contribution,margin:s.margin});
const scenarios=[640,620,660,680,700,720,740].map(cutoff=>summarize(P.simulate(data,{...config,cutoff})));
const parity=JSON.parse(fs.readFileSync(path.join(root,'analysis/scoring-parity.json'),'utf8'));
for(const [i,row] of parity.entries())check(`Browser PD matches scikit-learn ${i+1}`,Math.abs(P.predict(data,row.application,row.amount)-row.pd)<1e-8);
const result={passed:tests.every(t=>t.passed),tests,baseline:summarize(baseline),scenarios,planning_loss_multiplier:loss};
fs.writeFileSync(path.join(root,'checks/policy_checks.json'),JSON.stringify(result,null,2)+'\n');
fs.writeFileSync(path.join(root,'analysis/policy-report.json'),JSON.stringify({baseline:summarize(baseline),scenarios,planning_loss_multiplier:loss},null,2)+'\n');
console.log(JSON.stringify({tests:tests.length,passed:result.passed,scenarios},null,2));if(!result.passed)process.exit(1);
