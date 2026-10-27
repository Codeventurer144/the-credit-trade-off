/* Shared browser/Node implementation; inputs and currency are in naira. */
(function(root){
'use strict';
function sigmoid(z){return 1/(1+Math.exp(-Math.max(-35,Math.min(35,z))));}
function predict(data,a,amount){
 const term=a[8],income=a[4];
 const x=[a[3]/100,Math.log(income),a[6]/income,(a[6]+amount*(1+.03*term)/term)/income,term,a[2]==='repeat'?1:0];
 const m=data.model;let z=m.intercept;
 x.forEach((v,i)=>{z+=(v-m.mean[i])/m.scale[i]*m.coef[i];});return sigmoid(z);
}
function simulate(data,config={},segment='all',includeRows=true){
 const cfg={cutoff:640,ceiling:.25,funding:.20,loss:1,growth:.03,...config};
 let denominator=0,approved=0,eligible=0;let principal=0,expectedLoss=0,revenue=0,funding=0,acquisition=0,servicing=0,collections=0;const rows=[];
 for(const a of data.population){
  if(segment!=='all'&&a[2]!==segment)continue;
  const [id,dt,sg,score,income,essential,debt,request,term,riskcap,blocked]=a;
  if(income!==null||blocked)denominator++;
  if(blocked||income===null)continue;
  const paymentCapacity=Math.max(0,Math.min(cfg.ceiling*income-debt,income-essential-debt-data.meta.residual_floor));
  const affordable=Math.floor(paymentCapacity*term/(1+.03*term)/1000)*1000;
  const amount=Math.min(request,data.meta.max_loan,riskcap,affordable);
  if(amount>=10000)eligible++;
  const pass=amount>=10000&&score>=cfg.cutoff;
  const burden=(debt+Math.max(0,amount)*(1+.03*term)/term)/income;
  if(includeRows)rows.push({id,date:dt,segment:sg,score,income,debt,essential,request,term,amount:Math.max(0,amount),pass,burden});
  if(!pass)continue;
  approved++;
  const pd=predict(data,a,amount),loss=data.loss_parameters[String(term)],weight=data.meta.conversion;
  const el=Math.min(amount,amount*pd*loss.ead_factor*loss.lgd*cfg.loss);
  principal+=amount*weight;expectedLoss+=el*weight;
  // Lifetime management forecast: interest haircut is an explicit heuristic.
  revenue+=amount*.03*term*(1-pd*.5)*weight;
  funding+=(amount*(term+1)/2*30.4375/365+amount*pd*loss.ead_factor*90/365)*cfg.funding*weight;
  acquisition+=(sg==='repeat'?500:1500)*weight;
  servicing+=200*term*weight;
  collections+=(150*(.10+pd)+350*pd)*weight;
 }
 const contribution=revenue-expectedLoss-funding-acquisition-servicing-collections;
 return {config:cfg,denominator,approved,eligible,approval:denominator?approved/denominator:0,
  funded:approved*data.meta.conversion,principal,expectedLoss,lossRate:principal?expectedLoss/principal:0,
  revenue,funding,acquisition,servicing,collections,contribution,margin:revenue?contribution/revenue:0,rows};
}
const api={predict,simulate};if(typeof module==='object'&&module.exports)module.exports=api;else root.CreditPolicy=api;
})(typeof window==='undefined'?globalThis:window);
