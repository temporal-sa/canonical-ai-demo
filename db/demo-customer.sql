-- Demo customer for the web UI's default email (sa@temporal.io).
-- The dataset ships 59 customers; we add #60 so orders/purchases resolve.
\c music;

INSERT INTO customer (customer_id, first_name, last_name, company, address, city, state, country, postal_code, phone, email, support_rep_id)
VALUES (60, 'Temporal', 'SA', 'Temporal Technologies', '999 Third Ave', 'Seattle', 'WA', 'USA', '98104', '+1 (555) 555-0100', 'sa@temporal.io', 3);
