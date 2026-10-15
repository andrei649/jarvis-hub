"""Stable, public business catalog."""


def catalog() -> dict:
    return {
        "templates": [
            {"id": "ecommerce", "name": "E-commerce", "description": "Online orders and stock", "departments": ["Sales", "Operations", "Support"]},
            {"id": "automotive", "name": "Automotive", "description": "Vehicle sales and customer pipeline", "departments": ["Sales", "Service", "Operations"]},
            {"id": "services", "name": "Services", "description": "Client work and sales pipeline", "departments": ["Sales", "Delivery", "Finance"]},
        ],
        "connectors": [
            {"id": "woocommerce", "name": "WooCommerce", "description": "Read orders and products", "category": "commerce", "auth_fields": [{"key": "consumer_key", "label": "Consumer key", "secret": True}, {"key": "consumer_secret", "label": "Consumer secret", "secret": True}], "base_url_required": True},
            {"id": "hubspot", "name": "HubSpot", "description": "Read deals", "category": "crm", "auth_fields": [{"key": "access_token", "label": "Access token", "secret": True}], "base_url_required": True},
            {"id": "csv", "name": "CSV", "description": "Import a local CSV file", "category": "file", "auth_fields": [], "base_url_required": False},
        ],
        "workflows": [
            {"id": "sales_overview", "name": "Sales overview", "description": "Paid sales by currency", "requires": "orders"},
            {"id": "stock_watch", "name": "Stock watch", "description": "Product stock and shortages", "requires": "products"},
            {"id": "pipeline_review", "name": "Pipeline review", "description": "Deals by stage and currency", "requires": "deals"},
        ],
    }
