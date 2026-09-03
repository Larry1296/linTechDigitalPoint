export type Identity = {
  id?: number;
  username?: string;
  first_name?: string;
  email?: string;
  authenticated: boolean;
  is_staff: boolean;
  is_superuser: boolean;
  roles: string[];
  permissions: string[];
  customer_profile?: { phone: string } | null;
};
export type Product = {
  id: number;
  product_name: string;
  slug: string;
  description: string;
  category: string;
  brand: string | null;
  images: { url: string; alt: string }[];
  name: string;
  sku: string;
  barcode: string | null;
  selling_price: string;
  available: string | null;
};
export type CartItem = {
  id: number;
  variant: number;
  product_name: string;
  variant_name: string;
  sku: string;
  quantity: string;
  unit_price: string;
  line_total: string;
  available: string;
};
export type Cart = { id: number; items: CartItem[]; total: string };
export type Shelf = {
  id: number;
  code: string;
  display_name: string;
  physical_label: string;
  zone: number;
  level: number | null;
  stack_id: number | null;
  stack_name: string | null;
  level_number: number | null;
  position_in_level: number | null;
  x: string;
  y: string;
  width: string;
  height: string;
  depth: string | null;
  rotation: string;
  active: boolean;
  total_quantity: string;
  contents: {
    lot__variant_id: number;
    lot__variant__product__name: string;
    lot__variant__name: string;
    quantity: string;
    reserved: string;
  }[];
};
export type ShelfLevel = {
  id: number;
  stack: number;
  level_number: number;
  y_position: string;
  height: string;
  active: boolean;
  shelves: Shelf[];
};
export type ShelfStack = {
  id: number;
  zone: number;
  zone_name: string;
  code: string;
  display_name: string;
  x: string;
  y: string;
  width: string;
  height: string;
  depth: string;
  rotation: string;
  number_of_levels: number;
  active: boolean;
  notes: string;
  measurement_unit: string;
  levels: ShelfLevel[];
};
export type Zone = {
  id: number;
  code: string;
  name: string;
  width: string;
  height: string;
  active: boolean;
  stacks: ShelfStack[];
  unassigned_shelves: Shelf[];
  shelves: Shelf[];
};
export type Order = {
  id: number;
  number: string;
  status: string;
  payment_status: string;
  fulfillment_status: string;
  fulfillment_method: string;
  total: string;
  created_at: string;
  payment_method: string;
  items: {
    id: number;
    product_name: string;
    variant_name: string;
    quantity: string;
    unit_price: string;
    pick_locations?:
      | {
          shelf_id: number;
          shelf_code: string;
          shelf_name: string;
          zone: string;
          stack: string | null;
          level: number | null;
          quantity: string;
        }[]
      | null;
  }[];
};
