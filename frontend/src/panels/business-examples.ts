// Panel-local copies of examples/business/*.csv: Vite's frontend root denies raw imports outside it.
export const ordersExample = `id,status,total,currency,created_at
demo-order-001,completed,249.90,RON,2026-10-01T10:15:00Z
demo-order-002,processing,89.50,RON,2026-10-02T13:30:00Z
demo-order-003,cancelled,120.00,RON,2026-10-03T09:00:00Z
`;

export const productsExample = `id,name,stock_quantity
demo-product-001,Lampă de birou,12
demo-product-002,Cablu USB-C,3
demo-product-003,Adaptor universal,-2
demo-product-004,Produs fără stoc cunoscut,
`;

export const dealsExample = `id,name,amount,currency,stage
demo-deal-001,Proiect consultanță,3500.00,EUR,qualified
demo-deal-002,Abonament suport,850.00,EUR,proposal
demo-deal-003,Implementare CRM,4200.00,RON,closedwon
`;
