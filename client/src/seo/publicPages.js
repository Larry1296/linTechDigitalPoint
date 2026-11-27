// The public pages search engines and link previews (WhatsApp, Facebook, LinkedIn, X) may read.
// One list serves the router, the title kept in the browser tab, and the build, which writes each page
// as its own HTML file with its own title, description and plain text (see seoPages in vite.config.js).
// Everything said here must be true of the product: it is taken from the live plans and the home page.
export const SITE_URL = "https://dukaflow.co.ke";

export const PUBLIC_PAGES = [
  {
    path: "/",
    title: "DukaFlow – POS, Inventory & M-Pesa for Kenyan Businesses",
    description: "Point of sale, stock, services, M-Pesa agency, customer credit, expenses and reports for Kenyan businesses. First month free, then from KES 500 a month.",
    heading: "DukaFlow: POS, inventory and M-Pesa for Kenyan businesses",
    text: [
      "DukaFlow brings your stock, counter sales, services and business records into one workspace. Record cash and M-Pesa payments with each sale, run an M-Pesa agency, keep track of what customers owe, and see your sales, expenses and profit in reports built from your own records.",
      "Give each member of staff their own sign-in and role, and run more than one branch. The first month is free; after that plans start at KES 500 a month, paid by M-Pesa.",
    ],
  },
  {
    path: "/features",
    title: "Features – DukaFlow POS, Stock, M-Pesa Agency & Reports",
    description: "Point of sale with receipts, stock across shelves and locations, services and jobs, M-Pesa agency, M-KOPA phones, customer credit, expenses, profit & loss and staff roles.",
    heading: "DukaFlow features",
    text: [
      "Point of sale and receipts, with cash and M-Pesa payments recorded on each sale. Products and stock, with shelves and locations and a history of every delivery received.",
      "Services and jobs, menu and kitchen for eateries, rooms and guests' bills, M-Pesa agency, M-KOPA phones, customers and credit, expenses, profit and loss and balance sheet, more than one branch, staff accounts and roles, and chama management.",
    ],
  },
  {
    path: "/pricing",
    title: "Pricing – DukaFlow | First Month Free, Then From KES 500",
    description: "Try DukaFlow free for the first month. Basic is KES 500 a month and Pro, with every feature, is KES 1,000 a month, paid by M-Pesa. Change plan any time.",
    heading: "DukaFlow pricing",
    text: [
      "The first month is free on the plan you choose. After that, Basic is KES 500 a month and Pro, with every feature including reports, more than one branch and staff roles, is KES 1,000 a month.",
      "Plans are paid monthly by M-Pesa, and you can change plan any time.",
    ],
  },
  {
    path: "/about",
    title: "About DukaFlow – Business Software for Kenyan Shops",
    description: "DukaFlow is a workspace for businesses that sell and serve: retail shops, service counters, eateries and mixed businesses, with each business's records kept private.",
    heading: "About DukaFlow",
    text: [
      "DukaFlow is made for businesses that sell and serve: retail shops, service counters, eateries, lodgings and mixed businesses. Stock, sales, services and payments share the same records, so a sale or a delivery shows up everywhere it matters.",
      "Each business has its own private workspace. Its products, transactions and reports stay inside it.",
    ],
  },
  {
    path: "/contact",
    title: "Contact DukaFlow – Support for Your Business Workspace",
    description: "Get help with DukaFlow, set up your business workspace, or sign in to the one you already have.",
    heading: "Contact DukaFlow",
    text: [
      "Questions about DukaFlow? Ask the assistant on our home page, or sign in to your workspace.",
      "New here? Register your business and the first month is free.",
    ],
  },
];

export const PUBLIC_PATHS = PUBLIC_PAGES.map((page) => page.path);

// Every page but the home page is linked with a trailing slash (/pricing/): the host answers /pricing/ with that page's
// own HTML, but sends /pricing (no slash) to the home page's. The router accepts both.
export const pageHref = (path) => (path === "/" ? "/" : `${path}/`);

export const pageUrl = (path) => SITE_URL + pageHref(path);

// The public pages other than home are sections of the one public page: /pricing/ opens it at #pricing.
export function sectionOf(pathname) {
  const path = pathname.replace(/\/+$/, "");
  return path && PUBLIC_PATHS.includes(path) ? path.slice(1) : null;
}

const escape = (value) => value.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Writes one page's title, description, links and plain text into the built index.html.
// Every tag it changes must be present, or the build stops rather than publish a page with the wrong tags.
export function applyPage(html, page) {
  const title = escape(page.title);
  const description = escape(page.description);
  const url = escape(pageUrl(page.path));
  const swaps = [
    [/<title>[^<]*<\/title>/, `<title>${title}</title>`],
    [/(<meta name="description" content=")[^"]*(")/, `$1${description}$2`],
    [/(<meta property="og:url" content=")[^"]*(")/, `$1${url}$2`],
    [/(<meta property="og:title" content=")[^"]*(")/, `$1${title}$2`],
    [/(<meta property="og:description" content=")[^"]*(")/, `$1${description}$2`],
    [/(<meta name="twitter:title" content=")[^"]*(")/, `$1${title}$2`],
    [/(<meta name="twitter:description" content=")[^"]*(")/, `$1${description}$2`],
    [/(<link rel="canonical" href=")[^"]*(")/, `$1${url}$2`],
    [/(<!-- page-text -->)[\s\S]*?(<!-- \/page-text -->)/,
      `$1\n      <h1>${escape(page.heading)}</h1>\n${page.text.map((line) => `      <p>${escape(line)}</p>`).join("\n")}\n      $2`],
  ];
  return swaps.reduce((out, [pattern, replacement]) => {
    if (!pattern.test(out)) throw new Error(`index.html is missing the tag for ${pattern}`);
    return out.replace(pattern, replacement);
  }, html);
}
