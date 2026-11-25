CREATE TABLE IF NOT EXISTS store_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(150) NOT NULL UNIQUE,
    password VARCHAR(128) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('Admin', 'Manager', 'Cashier'))
);

CREATE TABLE IF NOT EXISTS store_category (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS store_supplier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(150) NOT NULL,
    phone VARCHAR(30) NOT NULL,
    email VARCHAR(254)
);

CREATE TABLE IF NOT EXISTS store_product (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    barcode VARCHAR(13) NOT NULL UNIQUE CHECK (length(barcode) = 13),
    name VARCHAR(200) NOT NULL,
    category_id INTEGER NOT NULL,
    supplier_id INTEGER,
    sale_price DECIMAL(10, 2) NOT NULL CHECK (sale_price > 0),
    quantity DECIMAL(10, 2) NOT NULL CHECK (quantity >= 0),
    min_quantity DECIMAL(10, 2) NOT NULL DEFAULT 5.00 CHECK (min_quantity >= 0),
    expiry_date DATE NOT NULL,
    FOREIGN KEY (category_id) REFERENCES store_category(id) ON DELETE RESTRICT,
    FOREIGN KEY (supplier_id) REFERENCES store_supplier(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS store_sale (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cashier_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(12, 2) NOT NULL DEFAULT 0.00,
    payment_method VARCHAR(20) NOT NULL CHECK (payment_method IN ('Cash', 'Kaspi_QR', 'Card')),
    FOREIGN KEY (cashier_id) REFERENCES store_user(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS store_saleitem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity DECIMAL(10, 2) NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10, 2) NOT NULL CHECK (unit_price > 0),
    subtotal DECIMAL(12, 2) NOT NULL,
    FOREIGN KEY (sale_id) REFERENCES store_sale(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES store_product(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS store_stockreceipt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES store_supplier(id) ON DELETE RESTRICT,
    received_by_id INTEGER NOT NULL REFERENCES store_user(id) ON DELETE RESTRICT,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_amount DECIMAL(12, 2) NOT NULL DEFAULT 0,
    posted BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS store_stockreceiptitem (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_receipt_id INTEGER NOT NULL REFERENCES store_stockreceipt(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES store_product(id) ON DELETE RESTRICT,
    quantity DECIMAL(10, 2) NOT NULL CHECK (quantity > 0),
    purchase_price DECIMAL(10, 2) NOT NULL CHECK (purchase_price > 0),
    expiry_date DATE
);

CREATE TABLE IF NOT EXISTS store_stockmovement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id INTEGER NOT NULL REFERENCES store_user(id) ON DELETE RESTRICT,
    product_id INTEGER NOT NULL REFERENCES store_product(id) ON DELETE RESTRICT,
    username VARCHAR(150) NOT NULL,
    barcode VARCHAR(13) NOT NULL,
    product_name VARCHAR(200) NOT NULL,
    before DECIMAL(10, 2) NOT NULL,
    after DECIMAL(10, 2) NOT NULL,
    sale_item_id INTEGER UNIQUE REFERENCES store_saleitem(id) ON DELETE RESTRICT,
    receipt_item_id INTEGER UNIQUE REFERENCES store_stockreceiptitem(id) ON DELETE RESTRICT,
    reason VARCHAR(200) NOT NULL DEFAULT '',
    CONSTRAINT stock_movement_valid CHECK (
        before >= 0 AND after >= 0 AND (
            (sale_item_id IS NOT NULL AND receipt_item_id IS NULL AND after < before AND reason = '')
            OR (receipt_item_id IS NOT NULL AND sale_item_id IS NULL AND after > before AND reason = '')
            OR (sale_item_id IS NULL AND receipt_item_id IS NULL AND after <> before AND reason <> '')
        )
    )
);

CREATE INDEX IF NOT EXISTS stockmovement_product ON store_stockmovement(product_id);
CREATE INDEX IF NOT EXISTS stockmovement_actor ON store_stockmovement(actor_id);

CREATE TABLE IF NOT EXISTS store_receiptscansession (
    id CHAR(32) NOT NULL PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES store_user(id) ON DELETE CASCADE,
    receipt_id INTEGER REFERENCES store_stockreceipt(id) ON DELETE CASCADE,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    heartbeat_at DATETIME NOT NULL,
    closed BOOLEAN NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS store_receiptscanevent (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id CHAR(32) NOT NULL REFERENCES store_receiptscansession(id) ON DELETE CASCADE,
    request_id CHAR(32) NOT NULL,
    barcode VARCHAR(13) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    message VARCHAR(250) NOT NULL DEFAULT '',
    created_at DATETIME NOT NULL,
    CONSTRAINT unique_receipt_scan_request UNIQUE (session_id, request_id)
);

CREATE INDEX IF NOT EXISTS receiptscansession_owner ON store_receiptscansession(owner_id);
CREATE INDEX IF NOT EXISTS receiptscansession_receipt ON store_receiptscansession(receipt_id);
CREATE INDEX IF NOT EXISTS receiptscanevent_session ON store_receiptscanevent(session_id);
