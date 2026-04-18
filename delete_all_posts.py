import xmlrpc.client

ODOO_URL      = "https://span-ea-capstone.odoo.com"
ODOO_DB       = "span-ea-capstone"
ODOO_USER     = "nainil0512@gmail.com"
ODOO_PASSWORD = "Honey@0512"

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid    = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

post_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "search", [[]])
print(f"Found {len(post_ids)} posts — deleting ALL...")
models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD, "blog.post", "unlink", [post_ids])
print(f"✅ Deleted {len(post_ids)} posts!")