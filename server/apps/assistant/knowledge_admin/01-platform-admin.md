# Running the platform

## Where do I manage all the businesses?
As the platform administrator, open **Platform → All businesses** (/admin/platform). It lists every registered business with its owner, contact details, plan, subscription status, days left, staff count and payments, plus totals: businesses, on trial, paying, ended, expiring soon, complimentary, revenue this month and in total.

## How do trials work?
Every new business gets a free trial of 30 days with all the tools of the plan it chose. When the trial ends without payment the subscription ends: the business can still record counter sales and look at products, services and customers, but the other tools are read-only until it pays.

## How do I change a business's plan, extend it or suspend it?
Open the business on **All businesses**, then **Change the subscription**. You can switch the plan, set the status (trial, active, suspended or cancelled), set the end date or **Add days**, and mark it complimentary (free, never ends). Each change is written to that business's activity log as done by the platform administrator.

## How do I record a payment received outside the app?
Open the business, then **Record a payment received outside the app**: choose the plan, the amount and, if there is one, the receipt number. The subscription is extended by the plan's period, the same as a payment made in the app.

## How do businesses pay in the app?
By M-Pesa (STK push to the owner's phone) through Safaricom Daraja. It works only when the server settings MPESA_MODE (off, sandbox, production or simulate), MPESA_CONSUMER_KEY, MPESA_CONSUMER_SECRET, MPESA_SHORTCODE, MPESA_PASSKEY and MPESA_CALLBACK_BASE_URL (a public https address Safaricom can reach) are set; for a till also MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline and MPESA_PARTY_B. Until then owners cannot pay in the app, and the admin page says so; you can still record their payments by hand.

Businesses can also send their own customers M-Pesa prompts from the point of sale, to their own till or paybill (each owner enters their Daraja keys in Settings → M-Pesa payments). That needs only MPESA_CALLBACK_BASE_URL on the server, the public https address Safaricom reports results to; without it the setup page says so and prompts stay off. The businesses' secrets are stored encrypted with FIELD_ENCRYPTION_KEY (a Fernet key; if unset, one derived from SECRET_KEY). Changing either key makes the saved secrets unreadable and owners must enter them again.

## What are the plans?
Plans are listed on **All businesses** under **Plans**: each has a price, a period in days and the tools it includes (products and stock, services and jobs, point of sale, customers and credit, expenses, M-Pesa agency, reports, shelves, staff, branches and chama management).

## How do new kinds of business get into the set-up list?
When an owner's business is not listed, they name it under "Other" when setting up (or later in Settings). It appears on **All businesses** under **Kinds of business added by owners**, with how many businesses described it and the tools and starter list the first owner chose; owners who type the same name add to its count instead of making a copy. Tidy its name, short description, search words, usual tools and product categories, then press **List for everyone**: new owners then find it in the list and start with those tools. **Take off the list** hides it from new owners; businesses already using it keep working.

# AI assistants

## Which AI chats are there?
Three. The public help chat on the website answers anyone from the public help articles only and never sees business records. Each business has its own assistant on every page of its workspace, which reads that business's records only, within the role of the person asking. The platform administrator's assistant is the same business assistant for their own business, plus these admin articles and a summary of all registered businesses (plans, status, payments, activity), never another business's sales, customers or money.

## How do I set up or check the AI keys?
The keys live only on the server, in the environment file: ANTHROPIC_API_KEY (Claude, needed for the public chat and the default business assistant) and, optionally, OPENAI_API_KEY (ChatGPT, a second choice owners can pick). After setting them, restart the server and run `python manage.py check_assistants`: it confirms each key and model without spending anything. Without a key the chats say they are not available and show the contact details.

## Can a business owner choose ChatGPT instead of Claude?
Yes, when OPENAI_API_KEY is set. The owner or an admin of a business chooses on their assistant's settings; BUSINESS_ASSISTANT_PROVIDER sets the default for everyone else.

## Does the business assistant learn from each business?
It does not need training. Every question is answered by looking up that business's live records at that moment, from the day the business was created: stock, sales, customers and what they owe, suppliers, money, the books, M-Pesa, loans, investments, chamas and the activity log. New records are known immediately, and one business's records are never used for another.
