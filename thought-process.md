# Thought process

## The decision I wanted to investigate

A lender can increase approvals and still make the business worse. I built this project around that tension: which applicants would receive credit under a different policy, could they afford it, and would the resulting loans cover expected losses and operating costs?

That question determines the six workspaces. Portfolio and vintages establish what has happened. Approvals and affordability examine a proposed policy. Collections tests an intervention. Profitability connects the proposal to its economic consequences. The dashboard opens directly into the analysis, with definitions available when needed.

## Why I used synthetic data

Public loan datasets rarely contain the complete sequence needed here: rejected applications, original decisions, instalment schedules, individual payments, daily arrears and randomised collection assignments. Combining unrelated datasets would create relationships that never existed. A coherent synthetic book lets every balance be reconstructed from cash and every experiment outcome traced to its assigned borrower.

The generator uses 50,000 applications over 18 months, followed by 12 months without new originations to observe later outcomes. Product limits, pricing, affordability rules and costs are assumptions. They are not Kuda data, Nigerian market estimates or evidence that the simulated treatment would work in production.

I retained hidden generator diagnostics for audit, then excluded them from analytical features. I also preserved missing income evidence as a review outcome. Inventing verified income to improve a chart would undermine the underwriting example.

## What the results say

At the default reporting date, the active book is **₦173.33m** and **9.6%** of principal is 30+ DPD. First-loan borrowers have a higher balance-weighted delinquency rate than repeat borrowers. That suggests an acquisition and seasoning question, rather than an immediate instruction to cut every borrower's limit.

The clearest policy comparison is a cut-off reduction from 640 to 620. Approvals rise from **54.0% to 63.0%**. Expected principal loss rises from about **4.2% to 4.7% of lending**, and three-month-pool contribution deteriorates from approximately **−₦6.49m to −₦8.92m** under the selected assumptions. More disbursements are therefore not a sufficient reason to approve the change.

Tightening the cut-off reduces the simulated loss, but it also removes substantial lending volume. Even the high-score scenarios do not establish an attractive broad lending business at the default pricing and costs. I would investigate funding and acquisition cost, repeat-borrower economics and product pricing before recommending a wider rollout. This result is conditional on the simulation; it is not a conclusion about Kuda's profitability.

The collections experiment offers a different kind of evidence. Treatment improves 14-day cure by **9.47 percentage points**, with an interval excluding zero, and increases net principal recovered per assigned borrower. Cost per cured borrower is nevertheless higher. That is why I show both the repayment outcome and its cost, rather than declaring the larger cure rate a complete success.

## Where I would be cautious

The temporal holdout exposes a model weakness: predicted default is 6.42% while observed default is 8.51%. AUC of 0.628 shows modest discrimination. I kept those results visible instead of selecting a flattering accuracy measure. The default 1.33× loss stress is a planning allowance for this shortfall, not a validated calibration fix.

Training loans have scores of at least 640. Estimates below that threshold extrapolate into applicants without funded outcomes. I would treat a lower-cut-off proposal as a candidate for a small, controlled pilot, with exposure limits and a defined loss stopping rule. The dashboard cannot resolve rejected-applicant selection bias.

Cohort deterioration also needs interpretation. The simulation's policy expansion overlaps a repayment stress period, so a higher vintage curve cannot identify which change caused the problem. Loan term, borrower mix and calendar timing need to be compared at equal maturity. Recent blank cells remain blank.

The financial forecast is deliberately labelled lifetime contribution by origination cohort. It does not claim to reproduce interest accrual, impairment accounting, taxes, corporate overhead or capital requirements. Its interest haircut and default-exposure timing are simplifications worth challenging before any real decision.

## How I checked the work

The data checks reconstruct principal and DPD independently from payment allocations, verify affordability limits and test experiment eligibility and follow-up. The policy checks confirm that the contribution bridge reconciles, stricter score rules cannot increase approvals, and funding costs cannot change underwriting decisions. They cover borrower segments and several score and affordability settings.

SQL keeps the historical definitions inspectable. Python prepares cohorts, evaluates the risk model and computes experiment intervals. A shared JavaScript engine powers both the live simulator and its checks. This makes an interaction traceable to a calculation, rather than a visual effect with a hard-coded number behind it.
