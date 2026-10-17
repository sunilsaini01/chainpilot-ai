// Codes for ids: warehouse SYN-WH1 instead of warehouse 1, and so on.
// The lists are small (a few warehouses and suppliers, up to 500 products).

import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Product, Supplier, Warehouse } from "../api/types";

export interface Lookups {
  warehouses: Warehouse[];
  warehouseCode: (id: number | null | undefined) => string;
  supplierCode: (id: number | null | undefined) => string;
  sku: (id: number) => string;
}

async function allProducts(): Promise<Product[]> {
  const products: Product[] = [];
  for (let offset = 0; offset < 2000; offset += 200) {
    const { data } = await api.products(offset);
    products.push(...data);
    if (data.length < 200) break;
  }
  return products;
}

export function useLookups(): Lookups {
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [products, setProducts] = useState<Product[]>([]);

  useEffect(() => {
    // Lookups only make tables nicer: if one fails, ids are shown instead.
    api.warehouses().then(({ data }) => setWarehouses(data)).catch(() => undefined);
    api.suppliers().then(({ data }) => setSuppliers(data)).catch(() => undefined);
    allProducts().then(setProducts).catch(() => undefined);
  }, []);

  const byId = <T extends { id: number }>(list: T[], id: number | null | undefined, field: keyof T) =>
    id == null ? "" : String(list.find((item) => item.id === id)?.[field] ?? `#${id}`);

  return {
    warehouses,
    warehouseCode: (id) => byId(warehouses, id, "code"),
    supplierCode: (id) => byId(suppliers, id, "code"),
    sku: (id) => byId(products, id, "sku"),
  };
}
