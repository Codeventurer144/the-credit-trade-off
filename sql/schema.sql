PRAGMA foreign_keys = ON;
CREATE TABLE borrowers (borrower_id TEXT PRIMARY KEY, income_type TEXT NOT NULL CHECK(income_type IN ('salary','self_employed')), created_date TEXT NOT NULL);
CREATE TABLE applications (
 application_id TEXT PRIMARY KEY, borrower_id TEXT NOT NULL REFERENCES borrowers, application_date TEXT NOT NULL,
 verified_income_kobo INTEGER, essential_costs_kobo INTEGER NOT NULL, existing_debt_kobo INTEGER NOT NULL,
 requested_kobo INTEGER NOT NULL, term_months INTEGER NOT NULL CHECK(term_months BETWEEN 1 AND 3),
 risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 300 AND 850), prior_funded_loans INTEGER NOT NULL,
 borrower_segment TEXT NOT NULL CHECK(borrower_segment IN ('first_loan','repeat')), policy_version TEXT NOT NULL,
 cutoff INTEGER NOT NULL, risk_cap_kobo INTEGER NOT NULL, affordable_cap_kobo INTEGER,
 assigned_kobo INTEGER NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('approved','declined','review')),
 decision_reason TEXT NOT NULL, accepted INTEGER NOT NULL CHECK(accepted IN (0,1))
);
CREATE TABLE income_observations (application_id TEXT NOT NULL REFERENCES applications, income_month TEXT NOT NULL, income_kobo INTEGER NOT NULL, PRIMARY KEY(application_id,income_month));
CREATE TABLE loans (loan_id TEXT PRIMARY KEY, application_id TEXT NOT NULL UNIQUE REFERENCES applications, disbursed_date TEXT NOT NULL,
 principal_kobo INTEGER NOT NULL CHECK(principal_kobo>0), term_months INTEGER NOT NULL, monthly_flat_rate REAL NOT NULL,
 final_due_date TEXT NOT NULL, default_date TEXT, ead_kobo INTEGER, writeoff_date TEXT, written_off_kobo INTEGER NOT NULL DEFAULT 0,
 payoff_date TEXT, recovery_window_complete INTEGER NOT NULL CHECK(recovery_window_complete IN (0,1)));
CREATE TABLE repayment_schedule (schedule_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES loans, instalment_number INTEGER NOT NULL,
 due_date TEXT NOT NULL, principal_due_kobo INTEGER NOT NULL, interest_due_kobo INTEGER NOT NULL, UNIQUE(loan_id,instalment_number));
CREATE TABLE payments (payment_id TEXT PRIMARY KEY, loan_id TEXT NOT NULL REFERENCES loans, payment_date TEXT NOT NULL,
 principal_kobo INTEGER NOT NULL, interest_kobo INTEGER NOT NULL, is_post_writeoff INTEGER NOT NULL CHECK(is_post_writeoff IN (0,1)));
CREATE TABLE payment_allocations (payment_id TEXT NOT NULL REFERENCES payments, schedule_id TEXT NOT NULL REFERENCES repayment_schedule,
 principal_kobo INTEGER NOT NULL, interest_kobo INTEGER NOT NULL, PRIMARY KEY(payment_id,schedule_id));
CREATE TABLE loan_snapshots (loan_id TEXT NOT NULL REFERENCES loans, snapshot_date TEXT NOT NULL,
 outstanding_principal_kobo INTEGER NOT NULL, days_past_due INTEGER NOT NULL, state TEXT NOT NULL,
 ever_30_dpd INTEGER NOT NULL, PRIMARY KEY(loan_id,snapshot_date));
CREATE TABLE loan_age_outcomes (loan_id TEXT NOT NULL REFERENCES loans, month_on_book INTEGER NOT NULL,
 anniversary_date TEXT NOT NULL, ever_30_dpd INTEGER NOT NULL, defaulted INTEGER NOT NULL,
 PRIMARY KEY(loan_id,month_on_book));
CREATE TABLE collection_assignments (assignment_id TEXT PRIMARY KEY, borrower_id TEXT NOT NULL UNIQUE REFERENCES borrowers,
 loan_id TEXT NOT NULL UNIQUE REFERENCES loans, assignment_date TEXT NOT NULL, arm TEXT NOT NULL CHECK(arm IN ('control','treatment')),
 opening_principal_kobo INTEGER NOT NULL, cured_14d INTEGER NOT NULL, recovered_principal_14d_kobo INTEGER NOT NULL,
 cost_kobo INTEGER NOT NULL, followup_complete INTEGER NOT NULL);
CREATE TABLE loan_costs (loan_id TEXT NOT NULL REFERENCES loans, cost_date TEXT NOT NULL, cost_type TEXT NOT NULL,
 amount_kobo INTEGER NOT NULL, PRIMARY KEY(loan_id,cost_date,cost_type));
CREATE TABLE principal_events (loan_id TEXT NOT NULL REFERENCES loans, event_date TEXT NOT NULL,
 event_type TEXT NOT NULL, amount_kobo INTEGER NOT NULL);
CREATE TABLE simulation_truth (loan_id TEXT PRIMARY KEY REFERENCES loans, latent_payment_path TEXT NOT NULL,
 stress_factor REAL NOT NULL, synthetic_only INTEGER NOT NULL DEFAULT 1);
CREATE INDEX app_borrower_date ON applications(borrower_id,application_date);
CREATE INDEX payments_loan_date ON payments(loan_id,payment_date);
CREATE INDEX snapshots_date ON loan_snapshots(snapshot_date);
CREATE INDEX principal_event_date ON principal_events(event_date);
CREATE INDEX schedule_loan ON repayment_schedule(loan_id);

CREATE INDEX allocations_schedule ON payment_allocations(schedule_id);
CREATE INDEX events_loan_date ON principal_events(loan_id,event_date);
