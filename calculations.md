# Calculations

Amounts in the raw tables are integer kobo. The dashboard and policy engine use naira. Historical results stop at the selected observation date; the default is 30 June 2025. The policy simulator evaluates the same 8,312 applications submitted from April through June 2025. All records are synthetic.

## Portfolio balances and losses

Outstanding principal is disbursed principal less principal repayments and write-offs. Later recoveries reduce realised credit loss, not outstanding principal a second time. Payments post before the day's delinquency assessment. DPD follows the oldest unpaid contractual instalment, including interest.

For June, outstanding principal is **₦173,331,151.35**. Principal on loans at 30+ DPD is **₦16,665,154.91**. Dividing the second by the first gives **9.61%**; the dashboard displays 9.6%.

Monthly net principal loss is write-offs less post-write-off principal recoveries. June's net loss is **₦3,405,267.78**. Its average daily active principal is **₦173,546,594.02**. The annualised rate is:

`3,405,267.78 / 173,546,594.02 × 365 / 30 = 23.87%`

Daily balances are reconstructed from signed principal events. `monthly_financials` weights each event by the days it affects the selected month. The validation script independently sums a full month's daily balances to check that shortcut. An annualised monthly rate extrapolates realised loss; it is not a prediction of the coming year.

See `sql/reporting_views.sql`, `principal_events` and `checks/validate_data.py`.

## Decisions and affordable amounts

Approval rate divides approved applications by decided applications. Missing-income reviews are excluded; eligibility declines are included. In the policy pool, the baseline approves **4,389 of 8,121 decided applications: 54.05%**. Lowering the score cut-off from 640 to 620 approves **5,115: 62.98%**, an increase of **8.94 percentage points**.

Income is the median of three previous complete months of verified recurring income. Maximum monthly payment is the lower of:

`repayment ceiling × income − existing debt repayments`

`income − essential expenses − existing debt repayments − ₦30,000`

Negative capacity becomes zero. For monthly flat interest `r` and term `t`, the supported principal is `payment capacity × t / (1 + r × t)`, rounded down to ₦1,000. The assigned amount is the minimum of this value, the request, the score-based cap and ₦150,000. Amounts below ₦10,000 fail affordability.

Example: income ₦240,000, essential costs ₦120,000, existing debt ₦20,000 and a 25% ceiling allow a ₦40,000 instalment. At three months and 3% flat monthly interest, capacity supports ₦110,000 principal after rounding. A ₦90,000 score cap reduces the offer to ₦90,000; its monthly repayment is ₦32,700.

See `assets/policy-engine.js`, shared by the dashboard and Node checks.

## Loan age and transitions

Ever-30-DPD at MOB 3 counts loans that reached 30 DPD by their third monthly anniversary, divided by originated loans with that observation available. Paid-off loans remain in the cohort denominator. Future anniversaries are omitted, not assigned zero. Calendar anniversaries and a 30-day delinquency threshold can behave differently around February.

A roll rate counts loans moving from opening state A to next month-end state B, divided by all loans opening in A. Paid-off and written-off destinations are retained. Each opening-state row sums to 100%. Cohort outcomes come from `loan_age_outcomes`; transitions use paired `loan_snapshots`.

## Collections experiment

One loan per borrower enters at 7 DPD. Cure means current or fully repaid 14 days after assignment. Every assigned borrower remains in the denominator, with complete follow-up required.

At 30 June, control cures **343 / 2,275 = 15.08%** and treatment cures **557 / 2,269 = 24.55%**. The difference is **9.47 percentage points**, with a **95% Newcombe interval of 7.16–11.77 points**, calculated from Wilson arm intervals. A two-sided Fisher exact test supplies the p-value. Assignment balance is checked against the intended 50/50 split using an exact binomial test.

Incremental net principal recovered per assigned borrower is treatment's mean recovery less control's mean recovery, less the difference in treatment costs: approximately **₦2,398**. This is recovery benefit, not interest revenue.

## Risk estimates and contribution

Logistic regression trains on **10,151 January–September 2024 loans** and is tested on **4,701 October–December loans**. A label requires observation through contractual maturity plus 90 days. Six application-time features enter the model; later payments and generator truth are excluded. Scaling parameters and coefficients are exported for identical browser scoring.

Holdout AUC is **0.628**. Observed default is **8.51%**, versus **6.42%** predicted. The default planning loss multiplier is their ratio rounded to **1.33×**; this adjustment has no independent validation claim.

Expected principal loss sums `PD × conditional EAD × conditional 180-day principal LGD × loss stress`. EAD factors and LGD use only defaults with complete recovery windows by 30 June. Term-level samples are 53, 117 and 285 loans. Proposed principal changes exposure and the model's repayment-burden feature.

Expected funded amounts use historical approval-to-funding conversion. Forecast interest is `principal × 3% × term × (1 − 0.5 × PD)`. Funding assumes amortising contractual exposure plus 90 additional days of conditional default exposure. These are explicit management approximations.

Contribution subtracts expected principal losses, funding, acquisition, servicing and collections from interest income. The baseline three-month pool produces approximately **−₦6.49m**; a 620 cut-off produces **−₦8.92m**. No expected loss is deducted again as a realised write-off. The six-cohort forecast applies selected volume growth to lifetime unit economics, not to calendar accounting income.
