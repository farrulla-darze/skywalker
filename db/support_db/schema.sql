-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Users table
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Merchants table
CREATE TABLE merchants (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    legal_name TEXT NOT NULL,
    trade_name TEXT NOT NULL,
    document TEXT NOT NULL,
    segment TEXT NOT NULL,
    onboarding_status TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Products enabled table
CREATE TABLE products_enabled (
    merchant_id TEXT PRIMARY KEY,
    maquininha INTEGER NOT NULL,
    tap_to_pay INTEGER NOT NULL,
    pix INTEGER NOT NULL,
    boleto INTEGER NOT NULL,
    link_pagamento INTEGER NOT NULL,
    conta_digital INTEGER NOT NULL,
    emprestimo INTEGER NOT NULL,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
);

-- Account status table
CREATE TABLE account_status (
    merchant_id TEXT PRIMARY KEY,
    balance_available REAL NOT NULL,
    balance_blocked REAL NOT NULL,
    transfers_enabled INTEGER NOT NULL,
    block_reason TEXT,
    last_transfer_at TEXT,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
);

-- Authentication status table
CREATE TABLE auth_status (
    user_id TEXT PRIMARY KEY,
    last_login_at TEXT,
    failed_login_attempts INTEGER NOT NULL,
    is_locked INTEGER NOT NULL,
    lock_reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Devices table
CREATE TABLE devices (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    type TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    last_seen_at TEXT,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
);

-- Transfers table
CREATE TABLE transfers (
    id TEXT PRIMARY KEY,
    merchant_id TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (merchant_id) REFERENCES merchants(id)
);

-- Incidents table
CREATE TABLE incidents (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    active INTEGER NOT NULL,
    description TEXT NOT NULL,
    started_at TEXT NOT NULL
);
