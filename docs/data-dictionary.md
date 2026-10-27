# Data dictionary

All records are synthetic. Dates are ISO calendar dates; money fields ending `_kobo` are integers (100 kobo = ₦1). Boolean fields use 0/1. Identifiers beginning `SYN-` carry no personal information. CSV empty fields represent SQL NULL, not zero.

## Relationships and grains

| Table | One row represents | Primary key | Links |
|---|---|---|---|
| borrowers | A synthetic customer | borrower_id | applications, collections |
| applications | A completed application | application_id | borrower_id |
| income_observations | A previous complete income month | application_id, income_month | applications |
| loans | A funded application | loan_id | unique application_id |
| repayment_schedule | A contractual instalment | schedule_id | loan_id |
| payments | Actual cash received on a date | payment_id | loan_id |
| payment_allocations | Payment allocated to an instalment | payment_id, schedule_id | payments, schedule |
| loan_snapshots | Loan position at month end | loan_id, snapshot_date | loans |
| loan_age_outcomes | Position at an exact monthly anniversary | loan_id, month_on_book | loans |
| collection_assignments | One borrower-level experiment assignment | assignment_id | unique borrower_id and loan_id |
| loan_costs | A cost type incurred by a loan on a date | loan_id, cost_date, cost_type | loans |
| principal_events | A balance-changing event | row identifier | loan_id |
| simulation_truth | Hidden generator diagnostic | loan_id | loans; excluded from analytical features |

## Applications and income

`borrowers.income_type` is salary or self-employed. `created_date` is first application date. A customer can apply repeatedly; a borrower with no prior funded loan remains a first-loan applicant even after earlier declined applications.

`applications.application_date` is the decision and, where applicable, disbursement date. `verified_income_kobo` is the median of three `income_observations`, each from a complete calendar month before application. Missing verification has no income-observation rows. `essential_costs_kobo` and `existing_debt_kobo` are monthly expenses and existing debt repayments known at application.

`requested_kobo` is requested principal. `term_months` is 1–3. `risk_score` is the synthetic application-time score. `prior_funded_loans` and `borrower_segment` count only loans disbursed no later than application. `policy_version` and `cutoff` preserve the actual historical rule.

`risk_cap_kobo` is the score-based cap. `affordable_cap_kobo` is the principal supported by the repayment and residual-income tests, rounded down to ₦1,000. `assigned_kobo` is zero for non-approved applications; for approved applications it is the minimum of the request, risk cap, affordability cap and ₦150,000. Missing verification produces a NULL affordability cap.

`decision` is approved, declined or review. `decision_reason` is the first applicable rule: prior default, open prior loan, missing income evidence, affordability, score cut-off, or policy pass. `accepted` records offer acceptance. A small proportion of accepted offers are not funded. All applications are completed records, but review cases are not decisions for the approval-rate denominator.

## Loan contracts and cash

`loans.principal_kobo` is the actual amount disbursed. `monthly_flat_rate` is 0.03; total scheduled interest equals principal × rate × term. Principal and total interest are divided across instalments, distributing rounding remainders without losing a kobo. `final_due_date` is the final contractual instalment date. Monthly anniversaries clamp to the final day of a shorter month.

`default_date` is first 90 DPD. `ead_kobo` is principal still unpaid after that day's payments. `writeoff_date` is first 120 DPD with remaining principal; `written_off_kobo` is that remaining principal. `payoff_date` is when all scheduled principal and interest have been received. `recovery_window_complete` states whether default + 180 days is observable by the full dataset endpoint. These are outcomes, not underwriting features.

`payments.principal_kobo` and `interest_kobo` record the allocation of received cash. A payment cannot exceed unpaid contractual amounts. `is_post_writeoff` identifies payments after the write-off date. Within each day cash posts before state assessment and write-off, so cash on the write-off date is a pre-write-off repayment.

`payment_allocations` reconciles every payment to individual instalments. Clear the oldest instalment's principal and interest before advancing to the next. DPD is based on the oldest due instalment with unpaid contractual amounts, including interest.

## Positions and loan age

`loan_snapshots.outstanding_principal_kobo` excludes written-off principal and interest. `days_past_due` is zero when no due contractual amount is unpaid. It can continue to rise after write-off while arrears remain. `state` is current, 1-29, 30-59, 60-89, 90+, paid_off or written_off. Written-off status remains identifiable after later recoveries. `ever_30_dpd` is historical and never reverses.

Snapshots run from the first month-end after funding through the first terminal month-end. A loan that closed or was written off does not produce redundant later snapshots; it no longer contributes active principal. The transition query retains the terminal destination. Do not treat the absence of later terminal rows as missing active-loan data.

`loan_age_outcomes` covers exact anniversaries from MOB 0 through MOB 6, using first-ever 30 DPD and default status as of each anniversary. At an earlier dashboard date, omit later anniversaries rather than treating them as observed zeroes. The default outcome horizon is contractual maturity plus 90 days, so use the appropriate MOB for each term.

## Collections, costs and balance ledger

`collection_assignments.assignment_date` is the first eligible 7-DPD episode. `opening_principal_kobo` is principal at assignment after that day's cash. `cured_14d` means current or fully paid at day 14; the denominator includes every randomised borrower, regardless of response. `recovered_principal_14d_kobo` counts principal received after assignment through day 14. The term recovery here refers to delinquent-loan collections, not exclusively post-write-off cash. `followup_complete` must be checked against the selected reporting date, not merely the full dataset endpoint.

`loan_costs.cost_type` is acquisition, servicing or collections. Collection expense is recorded once and reconciles to assignment costs. No fee income, corporate overhead, taxes or capital charges are modelled.

`principal_events.amount_kobo` is positive for disbursement and negative for pre-write-off principal repayments or write-offs. Post-write-off recoveries do not reduce outstanding principal a second time. Cumulative event amounts reconstruct the gross active principal book. They also permit exact daily average exposure through interval weighting.

`simulation_truth.latent_payment_path` and `stress_factor` describe data-generation choices. They exist only to audit the simulation. They are not observable borrower information and must never enter policy or model features.
