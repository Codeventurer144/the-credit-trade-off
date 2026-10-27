-- Operational dates are explicit. Never use future outcomes in an earlier snapshot.
CREATE VIEW monthly_applications AS
SELECT substr(application_date,1,7) AS month, policy_version, borrower_segment,
 count(*) AS completed_applications,
 sum(decision IN ('approved','declined')) AS decided_applications,
 sum(decision='review') AS reviews,
 sum(decision='approved') AS approvals,
 sum(accepted) AS accepted_offers,
 1.0*sum(decision='approved')/nullif(sum(decision IN ('approved','declined')),0) AS approval_rate
FROM applications GROUP BY 1,2,3;

CREATE VIEW monthly_portfolio AS
SELECT snapshot_date, sum(outstanding_principal_kobo) AS outstanding_principal_kobo,
 sum(outstanding_principal_kobo>0) AS active_loans,
 sum(CASE WHEN days_past_due>=30 THEN outstanding_principal_kobo ELSE 0 END) AS dpd30_principal_kobo,
 1.0*sum(CASE WHEN days_past_due>=30 THEN outstanding_principal_kobo ELSE 0 END)
 /nullif(sum(outstanding_principal_kobo),0) AS dpd30_balance_rate
FROM loan_snapshots GROUP BY snapshot_date;

CREATE VIEW monthly_loan_transitions AS
SELECT a.snapshot_date AS opening_date, a.state AS opening_state,
 coalesce(b.state,CASE WHEN l.writeoff_date<=date(a.snapshot_date,'start of month','+2 months','-1 day') THEN 'written_off'
 WHEN l.payoff_date<=date(a.snapshot_date,'start of month','+2 months','-1 day') THEN 'paid_off' END) AS ending_state,
 count(*) AS loans
FROM loan_snapshots a
JOIN loans l USING(loan_id)
LEFT JOIN loan_snapshots b ON b.loan_id=a.loan_id
 AND b.snapshot_date=date(a.snapshot_date,'start of month','+2 months','-1 day')
WHERE a.state NOT IN ('paid_off','written_off')
 AND date(a.snapshot_date,'start of month','+2 months','-1 day')<='2026-06-30'
GROUP BY 1,2,3;

-- Full follow-up endpoint only. Dashboard queries also filter anniversary_date <= :as_of.
CREATE VIEW vintage_curves AS
SELECT substr(l.disbursed_date,1,7) AS vintage, o.month_on_book,
 count(*) AS observed_loans, sum(o.ever_30_dpd) AS ever30_loans,
 1.0*sum(o.ever_30_dpd)/count(*) AS ever30_rate
FROM loan_age_outcomes o JOIN loans l USING(loan_id)
GROUP BY 1,2;

CREATE VIEW collection_results AS
SELECT arm, count(*) AS assigned_borrowers,sum(cured_14d) AS cured_borrowers,
 1.0*sum(cured_14d)/count(*) AS cure_rate,
 sum(recovered_principal_14d_kobo) AS recovered_principal_kobo,
 1.0*sum(recovered_principal_14d_kobo)/sum(opening_principal_kobo) AS recovery_rate,
 sum(cost_kobo) AS cost_kobo,
 1.0*sum(cost_kobo)/nullif(sum(cured_14d),0) AS cost_per_cured_kobo
FROM collection_assignments WHERE followup_complete=1 GROUP BY arm;

-- Average daily balances from balance-changing events: no millions of daily rows needed.
CREATE VIEW monthly_financials AS
WITH RECURSIVE months(month_start,month_end) AS (
 SELECT '2024-01-01','2024-01-31'
 UNION ALL SELECT date(month_start,'+1 month'),date(month_start,'+2 months','-1 day')
 FROM months WHERE month_start<'2026-06-01'
), exposures AS (
 SELECT m.month_start,m.month_end,
 sum(e.amount_kobo*(julianday(m.month_end)-julianday(max(e.event_date,m.month_start))+1.0))
 /(julianday(m.month_end)-julianday(m.month_start)+1) AS avg_daily_principal_kobo
 FROM months m LEFT JOIN principal_events e ON e.event_date<=m.month_end GROUP BY 1,2
), flows AS (
 SELECT m.*,
 coalesce((SELECT sum(principal_kobo) FROM loans WHERE disbursed_date BETWEEN m.month_start AND m.month_end),0) AS disbursed_kobo,
 coalesce((SELECT sum(written_off_kobo) FROM loans WHERE writeoff_date BETWEEN m.month_start AND m.month_end),0) AS written_off_kobo,
 coalesce((SELECT sum(principal_kobo) FROM payments WHERE is_post_writeoff=1 AND payment_date BETWEEN m.month_start AND m.month_end),0) AS recovered_kobo,
 coalesce((SELECT sum(interest_kobo) FROM payments WHERE payment_date BETWEEN m.month_start AND m.month_end),0) AS cash_interest_kobo,
 coalesce((SELECT sum(amount_kobo) FROM loan_costs WHERE cost_date BETWEEN m.month_start AND m.month_end),0) AS other_costs_kobo
 FROM exposures m
)
SELECT *,written_off_kobo-recovered_kobo AS net_principal_loss_kobo,
 (written_off_kobo-recovered_kobo)*365.0/nullif(avg_daily_principal_kobo*(julianday(month_end)-julianday(month_start)+1),0) AS annualised_net_loss,
 avg_daily_principal_kobo*.20*(julianday(month_end)-julianday(month_start)+1)/365.0 AS funding_cost_kobo,
 cash_interest_kobo-(written_off_kobo-recovered_kobo)-other_costs_kobo-
 avg_daily_principal_kobo*.20*(julianday(month_end)-julianday(month_start)+1)/365.0 AS cash_basis_contribution_kobo
FROM flows;
