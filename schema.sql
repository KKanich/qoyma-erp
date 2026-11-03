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
