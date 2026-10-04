// Photos that advertise what the platform does. Credits: public/images/home/README.md.
const photo = (name, alt, width = 1400, height = 934) => ({ src: `/images/home/${name}.jpg`, alt, width, height });

export const PHOTOS = {
  shopCounter: photo("shop-counter", "A shop owner smiling behind the counter of her well-stocked shop"),
  posCheckout: photo("pos-checkout", "A cashier tapping a tablet point-of-sale screen at the counter"),
  shopSale: photo("shop-sale", "A shopkeeper taking a customer's payment at the door of her shop"),
  stockShelves: photo("stock-shelves", "Rows of shelves stocked with labelled boxes", 1400, 1000),
  businessReports: photo("business-reports", "Sales charts and reports on a laptop screen"),
  teamMeeting: photo("team-meeting", "Three colleagues discussing plans around a laptop"),
  teamLead: photo("team-lead", "A confident team lead standing in front of a planning whiteboard", 1400, 935),
  ownerPhone: photo("owner-phone", "A butcher checking an order on his phone behind the counter"),
  shopfrontOwner: photo("shopfront-owner", "A shop owner standing proudly in the doorway of his shop", 1400, 985),
  ownerTablet: photo("owner-tablet", "A smiling business owner holding a tablet", 1280, 1600),
  marketStall: photo("market-stall", "A trader arranging fruit on his market stall", 1400, 935),
  phoneLaptop: photo("phone-laptop", "Someone working on a laptop with a phone in hand"),
  laptopCouch: photo("laptop-couch", "A business owner working on her laptop", 1068, 1600),
  laptopWork: photo("laptop-work", "A young man working on his laptop with his phone beside him", 1400, 1050),
  managerTablet: photo("manager-tablet", "A manager checking records on a tablet", 1067, 1600),
  officeDesk: photo("office-desk", "A business owner at her desk with a laptop and notebook"),
  groceryAisle: photo("grocery-aisle", "A shop aisle with fully stocked shelves on both sides", 1280, 1600),
  phoneRepair: photo("phone-repair", "A technician repairing a phone's circuit board", 900, 1600),
  repairBench: photo("repair-bench", "Gloved hands repairing a phone on a workbench", 1400, 788),
};

// Homepage hero: who the platform is for, then what they do with it.
export const HERO_SLIDES = [
  { ...PHOTOS.shopCounter, title: "Your shop", caption: "Built for the people behind the business" },
  { ...PHOTOS.shopSale, title: "Sales", caption: "Every sale and payment on record" },
  { ...PHOTOS.teamMeeting, title: "Your team", caption: "Everyone working from the same records" },
  { ...PHOTOS.ownerTablet, title: "Owners", caption: "Your business, in your hands" },
];

// Homepage "people" section.
export const PEOPLE_SLIDES = [
  { ...PHOTOS.teamLead, title: "Leading the team" },
  { ...PHOTOS.marketStall, title: "Market trade" },
  { ...PHOTOS.laptopWork, title: "Running the numbers" },
];

// Homepage photo band: each everyday job shows its own short slideshow.
export const WORK_TILES = [
  { title: "Receive and shelve stock", text: "Record deliveries, place them on shelves and see what's running low.",
    slides: [{ ...PHOTOS.stockShelves, title: "Stockroom" }, { ...PHOTOS.groceryAisle, title: "Shop shelves" }] },
  { title: "Sell and get paid", text: "Counter sales with cash and M-Pesa payments recorded against each sale.",
    slides: [{ ...PHOTOS.shopSale, title: "Payment" }, { ...PHOTOS.ownerPhone, title: "Orders" }] },
  { title: "Services and repairs", text: "Charge for repairs and other services, with the parts used taken from stock.",
    slides: [{ ...PHOTOS.phoneRepair, title: "Phone repair" }, { ...PHOTOS.repairBench, title: "Workbench" }] },
  { title: "Review your numbers", text: "Sales, expenses and stock value from the records you keep every day.",
    slides: [{ ...PHOTOS.businessReports, title: "Reports" }, { ...PHOTOS.officeDesk, title: "At the desk" }] },
];

// Sign-in pages: each page advertises the platform with its own photos (none repeat between pages).
export const AUTH_SLIDES = {
  login: [
    { ...PHOTOS.shopCounter, title: "Built for local business", heading: "Run your shop with confidence.",
      text: "Products, prices and stock for every counter, in a private workspace that belongs to your business." },
    { ...PHOTOS.posCheckout, title: "Point of sale", heading: "Sell faster at the counter.",
      text: "Search or scan a product, take cash or M-Pesa, and print the receipt in seconds." },
    { ...PHOTOS.businessReports, title: "Reports", heading: "See the bigger picture.",
      text: "Sales, expenses and profit trends built from your own records, not guesswork." },
    { ...PHOTOS.teamMeeting, title: "Your team", heading: "Give everyone the right access.",
      text: "Each member of staff gets their own sign-in and a role that shows only what they need." },
  ],
  register: [
    { ...PHOTOS.shopfrontOwner, title: "Start today", heading: "Your business deserves its own workspace.",
      text: "Create an account, add your business details and choose the tools you need." },
    { ...PHOTOS.ownerPhone, title: "Every kind of shop", heading: "From the butchery to the boutique.",
      text: "Products, services and stock set up the way your business actually works." },
    { ...PHOTOS.ownerTablet, title: "Owner first", heading: "You decide who sees what.",
      text: "Keep cost and profit to yourself, and give staff only the access they need." },
    { ...PHOTOS.marketStall, title: "Grow with confidence", heading: "Know what sells and what doesn't.",
      text: "Every sale is recorded, so your best sellers and slow movers are easy to spot." },
  ],
  forgotPassword: [
    { ...PHOTOS.laptopCouch, title: "Secure access", heading: "Your workspace stays private.",
      text: "Each business keeps its own products, sales and reports, away from every other subscriber." },
    { ...PHOTOS.laptopWork, title: "Anywhere you work", heading: "Back to business in minutes.",
      text: "Request a reset link and pick up exactly where you left off." },
    { ...PHOTOS.managerTablet, title: "Always in touch", heading: "Your records, whenever you need them.",
      text: "Check stock, sales and reports from the counter, the office or on the move." },
  ],
  resetPassword: [
    { ...PHOTOS.stockShelves, title: "Inventory", heading: "Know exactly where your stock is.",
      text: "Shelf-by-shelf locations, restock alerts and the real cost of every item you hold." },
    { ...PHOTOS.groceryAisle, title: "Stay stocked", heading: "Never run out of best sellers.",
      text: "Restock levels flag what's running low before your customers notice." },
    { ...PHOTOS.phoneRepair, title: "Services", heading: "Products and services, side by side.",
      text: "Charge for repairs and jobs, with the parts used taken straight from stock." },
    { ...PHOTOS.shopSale, title: "Payments", heading: "Every payment, accounted for.",
      text: "Each payment is recorded next to its sale, so the day's takings always add up." },
  ],
};
