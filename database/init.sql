CREATE TABLE IF NOT EXISTS customers (
    id VARCHAR(100) PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    status VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS sales (
    id VARCHAR(100) PRIMARY KEY,
    customer_id VARCHAR(100),
    seller TEXT,
    amount NUMERIC(14,2),
    sale_date DATE
);

INSERT INTO customers (id, name, city, status) VALUES
('001', 'Empresa A', 'Bogotá', 'active'),
('002', 'Empresa B', 'Cali', 'active'),
('003', 'Empresa C', 'Bogotá', 'inactive')
ON CONFLICT DO NOTHING;

INSERT INTO sales (id, customer_id, seller, amount, sale_date) VALUES
('S001', '001', 'Felipe', 150000, '2026-10-01'),
('S002', '001', 'Laura', 225000, '2026-10-02'),
('S003', '002', 'Felipe', 100000, '2026-10-03')
ON CONFLICT DO NOTHING;
