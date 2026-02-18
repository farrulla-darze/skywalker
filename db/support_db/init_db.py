import sqlite3
import os
from pathlib import Path

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "support.db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def init_database():
    """Initialize the support database with schema and seed data."""
    
    # Remove existing database file for idempotency
    if DB_PATH.exists():
        os.remove(DB_PATH)
        print(f"Removed existing database: {DB_PATH}")
    
    # Create new database connection
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Execute schema
    with open(SCHEMA_PATH, 'r') as f:
        schema_sql = f.read()
        cursor.executescript(schema_sql)
    
    print(f"Created database schema from {SCHEMA_PATH}")
    
    # Seed data
    seed_users(cursor)
    seed_merchants(cursor)
    seed_products_enabled(cursor)
    seed_account_status(cursor)
    seed_auth_status(cursor)
    seed_devices(cursor)
    seed_transfers(cursor)
    seed_incidents(cursor)
    
    # Commit and close
    conn.commit()
    conn.close()
    
    print(f"Database initialized successfully: {DB_PATH}")


def seed_users(cursor):
    """Seed users table with reference user and 50+ additional users."""
    
    users = [
        # Reference user for challenge scenarios
        ("client789", "João Silva Santos", "joao.silva@email.com", "+5511987654321", "active", "2025-01-15T10:30:00Z"),
        
        # Additional 50+ users
        ("client001", "Maria Oliveira Costa", "maria.oliveira@email.com", "+5511912345678", "active", "2024-06-10T08:15:00Z"),
        ("client002", "Carlos Eduardo Lima", "carlos.lima@email.com", "+5521987654321", "active", "2024-07-22T14:20:00Z"),
        ("client003", "Ana Paula Ferreira", "ana.ferreira@email.com", "+5531976543210", "active", "2024-08-05T09:45:00Z"),
        ("client004", "Roberto Alves Souza", "roberto.souza@email.com", "+5541965432109", "active", "2024-09-12T11:30:00Z"),
        ("client005", "Juliana Martins Rocha", "juliana.rocha@email.com", "+5551954321098", "active", "2024-10-18T16:00:00Z"),
        ("client006", "Fernando Santos Dias", "fernando.dias@email.com", "+5561943210987", "active", "2024-11-03T13:25:00Z"),
        ("client007", "Patricia Costa Nunes", "patricia.nunes@email.com", "+5571932109876", "active", "2024-12-01T10:50:00Z"),
        ("client008", "Ricardo Pereira Gomes", "ricardo.gomes@email.com", "+5581921098765", "active", "2025-01-08T15:15:00Z"),
        ("client009", "Camila Rodrigues Barros", "camila.barros@email.com", "+5591910987654", "active", "2025-01-20T12:40:00Z"),
        ("client010", "Marcos Vinicius Araujo", "marcos.araujo@email.com", "+5511909876543", "active", "2025-02-02T09:05:00Z"),
        
        ("client011", "Luciana Fernandes Silva", "luciana.silva@email.com", "+5521898765432", "active", "2024-05-15T08:30:00Z"),
        ("client012", "Paulo Henrique Cardoso", "paulo.cardoso@email.com", "+5531887654321", "active", "2024-06-20T14:45:00Z"),
        ("client013", "Beatriz Almeida Santos", "beatriz.santos@email.com", "+5541876543210", "active", "2024-07-10T11:20:00Z"),
        ("client014", "Gabriel Sousa Ribeiro", "gabriel.ribeiro@email.com", "+5551865432109", "active", "2024-08-25T16:35:00Z"),
        ("client015", "Renata Carvalho Moreira", "renata.moreira@email.com", "+5561854321098", "active", "2024-09-30T13:50:00Z"),
        ("client016", "Thiago Nascimento Pinto", "thiago.pinto@email.com", "+5571843210987", "active", "2024-10-12T10:15:00Z"),
        ("client017", "Vanessa Barbosa Teixeira", "vanessa.teixeira@email.com", "+5581832109876", "active", "2024-11-18T15:40:00Z"),
        ("client018", "Diego Monteiro Correia", "diego.correia@email.com", "+5591821098765", "active", "2024-12-22T12:05:00Z"),
        ("client019", "Amanda Freitas Cavalcanti", "amanda.cavalcanti@email.com", "+5511810987654", "active", "2025-01-05T09:30:00Z"),
        ("client020", "Rafael Cunha Azevedo", "rafael.azevedo@email.com", "+5521809876543", "active", "2025-01-28T14:55:00Z"),
        
        ("client021", "Larissa Melo Vieira", "larissa.vieira@email.com", "+5531798765432", "active", "2024-04-08T08:20:00Z"),
        ("client022", "Bruno Castro Mendes", "bruno.mendes@email.com", "+5541787654321", "active", "2024-05-19T13:45:00Z"),
        ("client023", "Isabela Ramos Farias", "isabela.farias@email.com", "+5551776543210", "active", "2024-06-28T10:10:00Z"),
        ("client024", "Leonardo Borges Machado", "leonardo.machado@email.com", "+5561765432109", "active", "2024-07-30T15:35:00Z"),
        ("client025", "Mariana Campos Duarte", "mariana.duarte@email.com", "+5571754321098", "active", "2024-08-14T12:00:00Z"),
        ("client026", "Gustavo Pires Moura", "gustavo.moura@email.com", "+5581743210987", "active", "2024-09-21T09:25:00Z"),
        ("client027", "Carolina Lopes Batista", "carolina.batista@email.com", "+5591732109876", "active", "2024-10-26T14:50:00Z"),
        ("client028", "Rodrigo Fonseca Reis", "rodrigo.reis@email.com", "+5511721098765", "active", "2024-11-30T11:15:00Z"),
        ("client029", "Aline Tavares Nogueira", "aline.nogueira@email.com", "+5521710987654", "active", "2024-12-15T16:40:00Z"),
        ("client030", "Felipe Moraes Castro", "felipe.castro@email.com", "+5531709876543", "active", "2025-01-10T13:05:00Z"),
        
        ("client031", "Tatiana Ribeiro Santana", "tatiana.santana@email.com", "+5541698765432", "active", "2024-03-12T08:30:00Z"),
        ("client032", "Vitor Hugo Andrade", "vitor.andrade@email.com", "+5551687654321", "active", "2024-04-25T13:55:00Z"),
        ("client033", "Daniela Soares Leal", "daniela.leal@email.com", "+5561676543210", "active", "2024-05-30T10:20:00Z"),
        ("client034", "Marcelo Dias Guimaraes", "marcelo.guimaraes@email.com", "+5571665432109", "active", "2024-07-05T15:45:00Z"),
        ("client035", "Priscila Goncalves Braga", "priscila.braga@email.com", "+5581654321098", "active", "2024-08-18T12:10:00Z"),
        ("client036", "Andre Luiz Medeiros", "andre.medeiros@email.com", "+5591643210987", "active", "2024-09-23T09:35:00Z"),
        ("client037", "Simone Amaral Figueiredo", "simone.figueiredo@email.com", "+5511632109876", "active", "2024-10-28T15:00:00Z"),
        ("client038", "Fabio Henrique Siqueira", "fabio.siqueira@email.com", "+5521621098765", "active", "2024-12-02T11:25:00Z"),
        ("client039", "Cristina Viana Pacheco", "cristina.pacheco@email.com", "+5531610987654", "active", "2025-01-07T16:50:00Z"),
        ("client040", "Leandro Silva Marques", "leandro.marques@email.com", "+5541609876543", "active", "2025-01-25T13:15:00Z"),
        
        ("client041", "Monica Rezende Paiva", "monica.paiva@email.com", "+5551598765432", "active", "2024-02-14T08:40:00Z"),
        ("client042", "Alexandre Torres Brito", "alexandre.brito@email.com", "+5561587654321", "active", "2024-03-28T14:05:00Z"),
        ("client043", "Elaine Macedo Rios", "elaine.rios@email.com", "+5571576543210", "active", "2024-04-30T10:30:00Z"),
        ("client044", "Sergio Coelho Xavier", "sergio.xavier@email.com", "+5581565432109", "active", "2024-06-12T15:55:00Z"),
        ("client045", "Adriana Pinheiro Caldeira", "adriana.caldeira@email.com", "+5591554321098", "active", "2024-07-18T12:20:00Z"),
        ("client046", "Claudio Esteves Matos", "claudio.matos@email.com", "+5511543210987", "active", "2024-08-22T09:45:00Z"),
        ("client047", "Silvia Rangel Lacerda", "silvia.lacerda@email.com", "+5521532109876", "active", "2024-09-27T15:10:00Z"),
        ("client048", "Mauricio Teles Sampaio", "mauricio.sampaio@email.com", "+5531521098765", "active", "2024-11-01T11:35:00Z"),
        ("client049", "Fernanda Bezerra Vasconcelos", "fernanda.vasconcelos@email.com", "+5541510987654", "active", "2024-12-10T17:00:00Z"),
        ("client050", "Henrique Bueno Chaves", "henrique.chaves@email.com", "+5551509876543", "active", "2025-01-18T13:25:00Z"),
        
        ("client051", "Raquel Furtado Neves", "raquel.neves@email.com", "+5561498765432", "suspended", "2024-01-20T08:50:00Z"),
        ("client052", "Edson Queiroz Prado", "edson.prado@email.com", "+5571487654321", "active", "2024-02-25T14:15:00Z"),
        ("client053", "Viviane Leite Camargo", "viviane.camargo@email.com", "+5581476543210", "active", "2024-03-30T10:40:00Z"),
    ]
    
    cursor.executemany(
        "INSERT INTO users (id, full_name, email, phone, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        users
    )
    
    print(f"Seeded {len(users)} users")


def seed_merchants(cursor):
    """Seed merchants table with reference merchant and additional merchants."""
    
    merchants = [
        # Reference merchant for challenge scenarios
        ("mrc_10291", "client789", "Silva Comercio de Alimentos LTDA", "Mercadinho do Silva", "12.345.678/0001-90", "retail", "approved"),
        
        # Additional merchants
        ("mrc_10001", "client001", "Oliveira Confeccoes LTDA", "Loja da Maria", "23.456.789/0001-01", "retail", "approved"),
        ("mrc_10002", "client002", "Lima Tech Solutions LTDA", "TechStore Carlos", "34.567.890/0001-12", "technology", "approved"),
        ("mrc_10003", "client003", "Ferreira Restaurante LTDA", "Sabor da Ana", "45.678.901/0001-23", "food_service", "approved"),
        ("mrc_10004", "client004", "Souza Auto Pecas LTDA", "Auto Pecas Roberto", "56.789.012/0001-34", "automotive", "approved"),
        ("mrc_10005", "client005", "Rocha Beauty Salon LTDA", "Salao Juliana", "67.890.123/0001-45", "beauty", "approved"),
        ("mrc_10006", "client006", "Dias Farmacia LTDA", "Farmacia Popular", "78.901.234/0001-56", "healthcare", "approved"),
        ("mrc_10007", "client007", "Nunes Livraria LTDA", "Livros & Cia", "89.012.345/0001-67", "retail", "approved"),
        ("mrc_10008", "client008", "Gomes Construcao LTDA", "Construtora RG", "90.123.456/0001-78", "construction", "approved"),
        ("mrc_10009", "client009", "Barros Moda Feminina LTDA", "Boutique Camila", "01.234.567/0001-89", "retail", "approved"),
        ("mrc_10010", "client010", "Araujo Informatica LTDA", "Tech Point", "12.345.678/0001-91", "technology", "approved"),
        
        ("mrc_10011", "client011", "Silva Padaria LTDA", "Padaria Luciana", "23.456.789/0001-02", "food_service", "approved"),
        ("mrc_10012", "client012", "Cardoso Materiais LTDA", "Casa de Construcao", "34.567.890/0001-13", "construction", "approved"),
        ("mrc_10013", "client013", "Santos Joias LTDA", "Joalheria Beatriz", "45.678.901/0001-24", "retail", "approved"),
        ("mrc_10014", "client014", "Ribeiro Esportes LTDA", "Mundo do Esporte", "56.789.012/0001-35", "retail", "approved"),
        ("mrc_10015", "client015", "Moreira Pet Shop LTDA", "Pet Mania", "67.890.123/0001-46", "retail", "approved"),
        ("mrc_10016", "client016", "Pinto Eletronicos LTDA", "Eletro Thiago", "78.901.234/0001-57", "technology", "approved"),
        ("mrc_10017", "client017", "Teixeira Flores LTDA", "Floricultura Vanessa", "89.012.345/0001-68", "retail", "approved"),
        ("mrc_10018", "client018", "Correia Pizzaria LTDA", "Pizza do Diego", "90.123.456/0001-79", "food_service", "approved"),
        ("mrc_10019", "client019", "Cavalcanti Moda LTDA", "Boutique Amanda", "01.234.567/0001-80", "retail", "approved"),
        ("mrc_10020", "client020", "Azevedo Moveis LTDA", "Moveis Rafael", "12.345.678/0001-92", "retail", "approved"),
        
        ("mrc_10021", "client021", "Vieira Cosmeticos LTDA", "Beleza Natural", "23.456.789/0001-03", "beauty", "approved"),
        ("mrc_10022", "client022", "Mendes Academia LTDA", "Fitness Bruno", "34.567.890/0001-14", "fitness", "approved"),
        ("mrc_10023", "client023", "Farias Optica LTDA", "Otica Isabela", "45.678.901/0001-25", "healthcare", "approved"),
        ("mrc_10024", "client024", "Machado Brinquedos LTDA", "Mundo dos Brinquedos", "56.789.012/0001-36", "retail", "approved"),
        ("mrc_10025", "client025", "Duarte Papelaria LTDA", "Papelaria Mariana", "67.890.123/0001-47", "retail", "approved"),
        ("mrc_10026", "client026", "Moura Lavanderia LTDA", "Lava Rapido", "78.901.234/0001-58", "services", "approved"),
        ("mrc_10027", "client027", "Batista Fotografias LTDA", "Studio Carolina", "89.012.345/0001-69", "services", "approved"),
        ("mrc_10028", "client028", "Reis Advocacia LTDA", "Escritorio Rodrigo Reis", "90.123.456/0001-70", "services", "approved"),
        ("mrc_10029", "client029", "Nogueira Contabilidade LTDA", "Contabil Aline", "01.234.567/0001-81", "services", "approved"),
        ("mrc_10030", "client030", "Castro Consultoria LTDA", "Consultoria FC", "12.345.678/0001-93", "services", "approved"),
        
        ("mrc_10031", "client031", "Santana Agencia LTDA", "Agencia Digital", "23.456.789/0001-04", "services", "approved"),
        ("mrc_10032", "client032", "Andrade Grafica LTDA", "Grafica Vitor", "34.567.890/0001-15", "services", "approved"),
        ("mrc_10033", "client033", "Leal Transportes LTDA", "Transportadora Daniela", "45.678.901/0001-26", "logistics", "approved"),
        ("mrc_10034", "client034", "Guimaraes Oficina LTDA", "Oficina Marcelo", "56.789.012/0001-37", "automotive", "approved"),
        ("mrc_10035", "client035", "Braga Escola LTDA", "Escola Priscila", "67.890.123/0001-48", "education", "approved"),
        ("mrc_10036", "client036", "Medeiros Clinica LTDA", "Clinica Andre", "78.901.234/0001-59", "healthcare", "approved"),
        ("mrc_10037", "client037", "Figueiredo Hotel LTDA", "Hotel Simone", "89.012.345/0001-60", "hospitality", "approved"),
        ("mrc_10038", "client038", "Siqueira Bar LTDA", "Bar do Fabio", "90.123.456/0001-71", "food_service", "approved"),
        ("mrc_10039", "client039", "Pacheco Cafeteria LTDA", "Cafe Cristina", "01.234.567/0001-82", "food_service", "approved"),
        ("mrc_10040", "client040", "Marques Sorveteria LTDA", "Sorveteria Leandro", "12.345.678/0001-94", "food_service", "approved"),
        
        ("mrc_10041", "client041", "Paiva Doceria LTDA", "Doces da Monica", "23.456.789/0001-05", "food_service", "approved"),
        ("mrc_10042", "client042", "Brito Churrascaria LTDA", "Churrasco Alexandre", "34.567.890/0001-16", "food_service", "approved"),
        ("mrc_10043", "client043", "Rios Lanchonete LTDA", "Lanchonete Elaine", "45.678.901/0001-27", "food_service", "approved"),
        ("mrc_10044", "client044", "Xavier Supermercado LTDA", "Supermercado Sergio", "56.789.012/0001-38", "retail", "approved"),
        ("mrc_10045", "client045", "Caldeira Boutique LTDA", "Boutique Adriana", "67.890.123/0001-49", "retail", "approved"),
        ("mrc_10046", "client046", "Matos Ferragens LTDA", "Ferragens Claudio", "78.901.234/0001-50", "retail", "approved"),
        ("mrc_10047", "client047", "Lacerda Calcados LTDA", "Calcados Silvia", "89.012.345/0001-61", "retail", "approved"),
        ("mrc_10048", "client048", "Sampaio Relojoaria LTDA", "Relojoaria Mauricio", "90.123.456/0001-72", "retail", "approved"),
        ("mrc_10049", "client049", "Vasconcelos Perfumaria LTDA", "Perfumaria Fernanda", "01.234.567/0001-83", "retail", "approved"),
        ("mrc_10050", "client050", "Chaves Instrumentos LTDA", "Instrumentos Musicais", "12.345.678/0001-95", "retail", "approved"),
        
        ("mrc_10051", "client051", "Neves Artesanato LTDA", "Artesanato Raquel", "23.456.789/0001-06", "retail", "pending_review"),
        ("mrc_10052", "client052", "Prado Bicicletaria LTDA", "Bike Shop Edson", "34.567.890/0001-17", "retail", "approved"),
        ("mrc_10053", "client053", "Camargo Jardinagem LTDA", "Jardinagem Viviane", "45.678.901/0001-28", "services", "approved"),
    ]
    
    cursor.executemany(
        "INSERT INTO merchants (id, user_id, legal_name, trade_name, document, segment, onboarding_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        merchants
    )
    
    print(f"Seeded {len(merchants)} merchants")


def seed_products_enabled(cursor):
    """Seed products_enabled table."""
    
    # Reference merchant with emprestimo disabled
    products = [
        ("mrc_10291", 1, 1, 1, 1, 1, 1, 0),
    ]
    
    # Add products for all other merchants (most with all products enabled)
    for i in range(1, 54):
        merchant_id = f"mrc_{10000 + i}"
        # Vary the products slightly
        emprestimo = 1 if i % 3 == 0 else 0
        link_pagamento = 1 if i % 5 != 0 else 0
        products.append((merchant_id, 1, 1, 1, 1, link_pagamento, 1, emprestimo))
    
    cursor.executemany(
        "INSERT INTO products_enabled (merchant_id, maquininha, tap_to_pay, pix, boleto, link_pagamento, conta_digital, emprestimo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        products
    )
    
    print(f"Seeded {len(products)} product configurations")


def seed_account_status(cursor):
    """Seed account_status table with transfer problem scenario."""
    
    # Reference merchant with blocked transfers
    accounts = [
        ("mrc_10291", 15420.50, 3200.00, 0, "pending_kyc_review", "2026-02-10T14:30:00Z"),
    ]
    
    # Add accounts for other merchants
    import random
    random.seed(42)  # Deterministic randomness
    
    for i in range(1, 54):
        merchant_id = f"mrc_{10000 + i}"
        balance_available = round(random.uniform(1000, 50000), 2)
        balance_blocked = round(random.uniform(0, 5000), 2) if i % 7 == 0 else 0.0
        transfers_enabled = 0 if i % 10 == 0 else 1
        block_reason = "compliance_review" if not transfers_enabled else None
        last_transfer = f"2026-02-{random.randint(1, 12):02d}T{random.randint(8, 18):02d}:00:00Z"
        
        accounts.append((merchant_id, balance_available, balance_blocked, transfers_enabled, block_reason, last_transfer))
    
    cursor.executemany(
        "INSERT INTO account_status (merchant_id, balance_available, balance_blocked, transfers_enabled, block_reason, last_transfer_at) VALUES (?, ?, ?, ?, ?, ?)",
        accounts
    )
    
    print(f"Seeded {len(accounts)} account statuses")


def seed_auth_status(cursor):
    """Seed auth_status table with login problem scenario."""
    
    # Reference user with locked account
    auth_statuses = [
        ("client789", "2026-02-11T08:45:00Z", 5, 1, "too_many_failed_attempts"),
    ]
    
    # Add auth status for other users
    import random
    random.seed(42)
    
    for i in range(1, 54):
        user_id = f"client{i:03d}"
        last_login = f"2026-02-{random.randint(1, 13):02d}T{random.randint(6, 22):02d}:00:00Z"
        failed_attempts = random.randint(0, 2) if i % 15 != 0 else random.randint(3, 5)
        is_locked = 1 if failed_attempts >= 5 else 0
        lock_reason = "too_many_failed_attempts" if is_locked else None
        
        auth_statuses.append((user_id, last_login, failed_attempts, is_locked, lock_reason))
    
    cursor.executemany(
        "INSERT INTO auth_status (user_id, last_login_at, failed_login_attempts, is_locked, lock_reason) VALUES (?, ?, ?, ?, ?)",
        auth_statuses
    )
    
    print(f"Seeded {len(auth_statuses)} auth statuses")


def seed_devices(cursor):
    """Seed devices table."""
    
    # Reference device
    devices = [
        ("dev_4451", "mrc_10291", "smart_pos", "maquininha_smart", "active", "2025-01-20T10:00:00Z", "2026-02-12T18:30:00Z"),
    ]
    
    # Add devices for merchants
    import random
    random.seed(42)
    
    device_types = ["smart_pos", "mobile_pos", "tap_to_pay_device"]
    device_models = ["maquininha_smart", "maquininha_pro", "tap_device_v2", "mobile_reader"]
    device_statuses = ["active", "inactive", "maintenance"]
    
    device_counter = 4452
    for i in range(1, 54):
        merchant_id = f"mrc_{10000 + i}"
        # Some merchants have multiple devices
        num_devices = random.randint(1, 3) if i % 5 == 0 else 1
        
        for _ in range(num_devices):
            device_id = f"dev_{device_counter}"
            device_type = random.choice(device_types)
            device_model = random.choice(device_models)
            device_status = random.choice(device_statuses) if i % 8 == 0 else "active"
            activated_at = f"2025-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}T10:00:00Z"
            last_seen = f"2026-02-{random.randint(1, 13):02d}T{random.randint(8, 20):02d}:00:00Z" if device_status == "active" else None
            
            devices.append((device_id, merchant_id, device_type, device_model, device_status, activated_at, last_seen))
            device_counter += 1
    
    cursor.executemany(
        "INSERT INTO devices (id, merchant_id, type, model, status, activated_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        devices
    )
    
    print(f"Seeded {len(devices)} devices")


def seed_transfers(cursor):
    """Seed transfers table with blocked and successful transfers."""
    
    # Reference merchant transfers
    transfers = [
        ("txf_blocked_001", "mrc_10291", 5000.00, "blocked", "account_blocked", "2026-02-11T15:20:00Z"),
        ("txf_success_001", "mrc_10291", 2500.00, "completed", None, "2026-02-09T11:30:00Z"),
    ]
    
    # Add transfers for other merchants
    import random
    random.seed(42)
    
    transfer_counter = 1000
    for i in range(1, 54):
        merchant_id = f"mrc_{10000 + i}"
        # Each merchant has 2-5 transfers
        num_transfers = random.randint(2, 5)
        
        for j in range(num_transfers):
            transfer_id = f"txf_{transfer_counter}"
            amount = round(random.uniform(100, 10000), 2)
            
            # Most transfers are completed
            if j == 0 and i % 10 == 0:
                status = "blocked"
                failure_reason = random.choice(["account_blocked", "insufficient_funds", "compliance_hold"])
            elif j == 0 and i % 15 == 0:
                status = "failed"
                failure_reason = "invalid_account"
            else:
                status = "completed"
                failure_reason = None
            
            created_at = f"2026-02-{random.randint(1, 13):02d}T{random.randint(8, 20):02d}:{random.randint(0, 59):02d}:00Z"
            
            transfers.append((transfer_id, merchant_id, amount, status, failure_reason, created_at))
            transfer_counter += 1
    
    cursor.executemany(
        "INSERT INTO transfers (id, merchant_id, amount, status, failure_reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        transfers
    )
    
    print(f"Seeded {len(transfers)} transfers")


def seed_incidents(cursor):
    """Seed incidents table with active and inactive incidents."""
    
    incidents = [
        # Active incident
        ("inc_pix_20260211", "pix", 1, "Temporary instability in Pix transfer processing", "2026-02-11T06:00:00Z"),
        
        # Additional incidents
        ("inc_boleto_20260210", "boleto", 0, "Boleto generation service was temporarily unavailable", "2026-02-10T14:00:00Z"),
        ("inc_maquininha_20260209", "maquininha", 0, "Smart POS devices experiencing connectivity issues", "2026-02-09T09:30:00Z"),
        ("inc_api_20260212", "api", 1, "Elevated API response times", "2026-02-12T12:00:00Z"),
        ("inc_login_20260208", "authentication", 0, "Login service degradation", "2026-02-08T16:45:00Z"),
    ]
    
    cursor.executemany(
        "INSERT INTO incidents (id, scope, active, description, started_at) VALUES (?, ?, ?, ?, ?)",
        incidents
    )
    
    print(f"Seeded {len(incidents)} incidents")


if __name__ == "__main__":
    init_database()
