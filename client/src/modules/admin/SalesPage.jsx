import { Fragment, useEffect, useState } from 'react';
import { api } from '../../core/api/client';
import { useAuth } from '../../core/auth/AuthContext';
import { ReceiptPanel } from '../receipts/ReceiptPanel';
import { ExplainProfitPanel } from './ExplainProfitPanel';
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { businessCurrency } from "../../core/organization/presentation";
import { FormError, FormSuccess } from "../../components/forms/FormNotice";
import { label, PAYMENT_METHODS } from "../../core/ui/labels";

const money = (value) => `${businessCurrency()} ${Number(value || 0).toLocaleString()}`;

// The one line shown for a sale until it is opened: when, which sale, who, what, how much and whether it is paid.
function SaleSummary({ sale }) {
  const when = new Date(sale.created_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const names = sale.items.map((i) => `${String(i.item).split(" — ")[0]}${Number(i.quantity) !== 1 ? ` × ${Number(i.quantity)}` : ""}`);
  const what = names.length > 2 ? `${names.slice(0, 2).join(", ")} and ${names.length - 2} more` : names.join(", ");
  const waiting = sale.payments.some((p) => ["PENDING", "MANUAL_REVIEW"].includes(p.status));
  const [label, tone] = sale.status === "REFUNDED" ? ["Returned and refunded", "muted"]
    : waiting && Number(sale.outstanding) <= 0 ? ["Paid twice? Check payments", "warn"]
    : waiting ? ["Waiting for M-Pesa confirmation", "warn"]
    : Number(sale.outstanding) > 0 ? [`Owes ${money(sale.outstanding)}`, "owed"] : ["Paid", "paid"];
  return <span className="saleSummary">
    <span className="saleWhen">{when}</span>
    <span className="saleWhat"><b>{what || "—"}</b><small>{sale.number} · {sale.customer}</small></span>
    <span className="saleAmount">{money(sale.charged ?? sale.total)}{Number(sale.charged) !== Number(sale.total) && sale.status === "COMPLETED" && <small>was {money(sale.total)}</small>}</span>
    <span className={`saleStatus ${tone}`}>{label}</span>
  </span>;
}

const METHOD_OPTIONS = PAYMENT_METHODS.map(([value, name]) => <option key={value} value={value}>{name}</option>);

export function SalesPage() {
  const { user }=useAuth();
  const [data,setData]=useState(null),[error,setError]=useState(''),[page,setPage]=useState(1),[busy,setBusy]=useState(false);
  const [key,setKey]=useState(() => crypto.randomUUID());
  const [receiptSale,setReceiptSale]=useState(null);
  const [explainItem,setExplainItem]=useState(null);
  const [notice,setNotice]=useState(null);
  const [failed,setFailed]=useState(null);
  const [search,setSearch]=useState(''),[owing,setOwing]=useState(false);
  const [customers,setCustomers]=useState([]);
  const can=(permission)=>user.permissions.includes(permission);
  const canSeeProfit=can('accounting.view_profit');
  const canCorrect=can('commerce.change_sale');
  const canNameDebtor=can('commerce.add_payment')&&can('accounts.view_customerprofile');
  const load=()=>api(`/api/v1/commerce/sales/?${new URLSearchParams({page,q:search.trim(),...(owing?{owing:'1'}:{})})}`).then(setData);
  useEffect(()=>{const timer=setTimeout(()=>{load().then(()=>setError('')).catch(e=>setError(e.message));},search?300:0);return()=>clearTimeout(timer);},[page,search,owing]);
  useEffect(()=>{if(canNameDebtor)api('/api/v1/commerce/customers/').then(list=>setCustomers(Array.isArray(list)?list:[])).catch(()=>{});},[canNameDebtor]);
  useLiveRefresh(load);
  const filter=(change)=>{setPage(1);setNotice(null);change();};
  // Once an action succeeds, fold its form and the sale away and bring the person back to the sale's line in the list,
  // where the updated status (Paid, Owes …) and a confirmation are shown. A failure stays in the open form, under its button.
  const submit=async(event,path,extra={},done='Saved.')=>{
    event.preventDefault();if(busy)return;setBusy(true);setFailed(null);setNotice(null);
    const form=event.currentTarget;
    const row=form.closest('.saleRow');
    try{await api(path,{method:'POST',body:JSON.stringify({...Object.fromEntries(new FormData(form)),...extra})});setKey(crypto.randomUUID());form.reset();
      for(let d=form.closest('details');d;d=d.parentElement?.closest('details'))d.open=false;
      setNotice({saleId:row?Number(row.dataset.saleId):null,text:done});await load();
      if(path.endsWith('/customers/'))api('/api/v1/commerce/customers/').then(list=>setCustomers(Array.isArray(list)?list:[])).catch(()=>{});
      const summary=row?.querySelector('summary');summary?.focus();summary?.scrollIntoView?.({block:'nearest'});}
    catch(e){setFailed({path,text:e.message});}finally{setBusy(false);}
  };
  const problem=(path,title)=>failed?.path===path&&<FormError title={title} message={failed.text} />;
  return <><h1>Sales and customer payments</h1>
    <div className="salesFilters" role="search">
      <label>Find a sale<input type="search" value={search} onChange={e=>{const value=e.target.value;filter(()=>setSearch(value));}} placeholder="Sale number, customer name or phone, or item" maxLength={80} /></label>
      <label className="checkLabel"><input type="checkbox" checked={owing} onChange={e=>{const value=e.target.checked;filter(()=>setOwing(value));}} /> Only sales that still owe money</label>
    </div>
    {error&&<FormError title="Could not load sales." message={error} />}
    {can('accounts.add_customerprofile')&&<details><summary>Add a customer</summary><form onSubmit={e=>submit(e,'/api/v1/commerce/customers/',{},'Customer saved. You can now pick them at the till or name them on a sale.')}><label>Name<input name="name" required maxLength="150" /></label><label>Phone<input name="phone" maxLength="30" /></label><button disabled={busy}>Save customer</button>{problem('/api/v1/commerce/customers/','Could not save the customer.')}</form></details>}{notice&&notice.saleId===null&&<FormSuccess message={notice.text} />}
    {!data ? <p>Loading sales…</p> : !data.count ? <p>{search||owing ? 'No sales match. Clear the search or untick "Only sales that still owe money" to see all sales.' : 'No sales yet. Your completed sales will appear here.'}</p> : <>{(search||owing)&&<p className="muted">{data.count} {data.count===1?'sale matches':'sales match'}.</p>}{data.results.map(s=>{
      const pay=`/api/v1/commerce/sales/${s.id}/payments/`, namePath=`/api/v1/commerce/sales/${s.id}/customer/`;
      return <Fragment key={s.id}><details className="saleRow" data-sale-id={s.id}><summary><SaleSummary sale={s} /></summary><section className="accountingPanel"><div className="saleHeading"><h2>{s.number}</h2><button type="button" className="secondary" onClick={()=>setReceiptSale(s.id)}>Receipt</button></div>
      <p>{s.customer} · {label(s.status)} · Total {money(s.charged ?? s.total)} · {Number(s.outstanding)>0?`Still owes ${money(s.outstanding)}`:'Nothing owed'}{s.due_date?` · Due ${s.due_date}`:''}</p>
      <ul className="saleLines">{s.items.map(i=><li key={i.id}><span>{Number(i.quantity)} × {i.item} @ {i.unit_price}{i.list_price&&Number(i.list_price)!==Number(i.unit_price)?<small className="muted"> (catalogue {i.list_price})</small>:null}{Number(i.discount)?<small className="muted"> · less {i.discount}</small>:null}{Number(i.returned_quantity)?<small className="muted"> · {Number(i.returned_quantity)} returned</small>:null}</span>
        {canSeeProfit&&<button type="button" className="linkButton" onClick={()=>setExplainItem(i.id)}>Explain profit</button>}</li>)}</ul>
      {Number(s.outstanding)>0&&!s.customer_id&&canNameDebtor&&<form className="saleAction" onSubmit={e=>submit(e,namePath,{},`${s.number} is now under the customer you chose.`)}><h3>Who owes this?</h3><p className="muted">This sale was rung up as Walk-in, so its unpaid {money(s.outstanding)} is not under any customer. Choose who owes it; the amounts do not change. This can be set once.</p>
        <label>Customer<select name="customer_id" required defaultValue=""><option value="" disabled>Choose the customer</option>{customers.map(c=><option key={c.id} value={c.id}>{c.name}{c.phone?` · ${c.phone}`:''}</option>)}</select></label>
        {!customers.length&&<p className="muted">No customers yet: use "Add a customer" at the top of this page first.</p>}<button disabled={busy||!customers.length}>Save customer</button>{problem(namePath,'Could not save the customer on this sale.')}</form>}
      {Number(s.outstanding)>0&&can('commerce.add_payment')&&<form className="saleAction" onSubmit={e=>submit(e,pay,{idempotency_key:key},`Payment recorded for ${s.number}.`)}><h3>Record a payment</h3>{s.payments.some(p=>['PENDING','MANUAL_REVIEW'].includes(p.status))&&<p className="formNotice" role="status">An M-Pesa payment on this sale is still waiting for confirmation (under Payments below). If that is this money, confirm it there instead of recording it again.</p>}<label>Amount received<input name="amount" type="number" step="0.01" min="0.01" max={s.outstanding} defaultValue={s.outstanding} required /></label><label>Paid by<select name="method">{METHOD_OPTIONS}</select></label><label>Reference (optional, e.g. the M-Pesa code)<input name="reference" maxLength="120" /></label><button disabled={busy}>Record payment</button>{problem(pay,'Could not record the payment.')}</form>}
      {s.payments.length>0&&<h3>Payments</h3>}
      {s.payments.map(p=>{const deletePath=`/api/v1/commerce/payments/${p.id}/delete/`, confirmPath=`/api/v1/commerce/payments/${p.id}/confirm/`;
        return <div key={p.id}><p>{label(p.method)} · {money(p.amount)} · {label(p.status)}</p>{['PENDING','MANUAL_REVIEW'].includes(p.status)&&can('commerce.change_payment')&&<>
          {Number(p.amount)>Number(s.outstanding)?<p className="formNotice" role="status">This sale is already paid by the other payment{s.payments.filter(o=>o.status==='COMPLETED').length===1?'':'s'} here ({s.payments.filter(o=>o.status==='COMPLETED').map(o=>`${label(o.method)} ${money(o.amount)}`).join(', ')}), so confirming this would count the money twice.
            Delete the payment that is wrong (Delete this payment, under it). If the customer paid by M-Pesa, delete the other payment first, then confirm this one.</p>
          :<form onSubmit={e=>submit(e,confirmPath,{},`Payment confirmed for ${s.number}.`)}><label>M-Pesa code from the confirmation message<input name="reference" required maxLength="120" defaultValue={p.reference||''} /></label>{p.reference&&<p className="muted">The code typed when the sale was made. Check it matches the SMS, then confirm.</p>}<button disabled={busy}>Confirm money received</button>{problem(confirmPath,'Could not confirm the payment.')}</form>}
          </>}
          {['COMPLETED','PENDING','MANUAL_REVIEW'].includes(p.status)&&can('accounting.reverse_cashentry')&&<details><summary>Delete this payment</summary><p className="muted">Use this when the payment was not done right: wrong method, wrong code, or recorded twice. {p.status==='COMPLETED'?'Its money comes back out and the sale shows what is still owed.':'It is dropped and never counted.'} Then record the right payment.</p><form onSubmit={e=>submit(e,deletePath,{},`Payment of ${money(p.amount)} deleted. ${s.number} now shows what is owed.`)}><label>Reason<input name="reason" required maxLength="240" placeholder="e.g. recorded twice" /></label><button className="danger" disabled={busy}>Delete payment</button>{problem(deletePath,'Could not delete the payment.')}</form></details>}</div>;})}
      {s.status==='COMPLETED'&&canCorrect&&<details><summary>Delete this sale</summary><p className="muted">Use this when the whole sale was recorded wrongly. It is taken out as if it never happened: goods go back on the shelf, its money and payments come out of {new Date(s.created_at).toLocaleDateString()}'s figures, and it disappears from your sales. Then record it again correctly.</p><form onSubmit={e=>submit(e,`/api/v1/commerce/sales/${s.id}/delete/`,{},`${s.number} deleted. Record the sale again if needed.`)}><label>Reason<input name="reason" required maxLength="240" placeholder="e.g. recorded wrongly, will record again" /></label><button className="danger" disabled={busy}>Delete sale</button>{problem(`/api/v1/commerce/sales/${s.id}/delete/`,'Could not delete the sale.')}</form></details>}
      {s.status==='COMPLETED'&&canCorrect&&<details><summary>Return some items</summary><form onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);const lines=s.items.map(i=>({item_id:i.id,quantity:f.get(`qty-${i.id}`),restock:f.get(`restock-${i.id}`)==='on'})).filter(l=>Number(l.quantity)>0);const refund=Number(f.get('refund')||0)>0?{method:f.get('refund_method'),amount:f.get('refund')}:null;submit(e,`/api/v1/commerce/sales/${s.id}/return-items/`,{lines,refund,reason:f.get('reason'),idempotency_key:key},`Return recorded for ${s.number}.`);}}>
        {s.items.map(i=><fieldset key={i.id} className="checkList"><legend>{i.item}</legend><label>Quantity returned<input name={`qty-${i.id}`} type="number" min="0" step="1" max={Number(i.quantity)-Number(i.returned_quantity)} defaultValue="0" /></label><label><input type="checkbox" name={`restock-${i.id}`} defaultChecked /> Back on the shelf (untick if damaged)</label></fieldset>)}
        <label>Reason<input name="reason" required maxLength="240" /></label>
        <label>Refund now (optional)<input name="refund" type="number" min="0" step="0.01" /></label>
        <label>Refund method<select name="refund_method">{METHOD_OPTIONS}</select></label>
        <button disabled={busy}>Record return</button>{problem(`/api/v1/commerce/sales/${s.id}/return-items/`,'Could not record the return.')}</form></details>}
      {s.status==='COMPLETED'&&canCorrect&&<details><summary>Change the price after the sale</summary><form onSubmit={e=>submit(e,`/api/v1/commerce/sales/${s.id}/notes/`,{idempotency_key:key},`Price correction recorded for ${s.number}.`)}>
        <label>Change<select name="kind"><option value="CREDIT">Lower the price: customer owes less</option><option value="DEBIT">Raise the price: customer owes more</option></select></label>
        <label>Amount<input name="amount" type="number" min="0.01" step="0.01" required /></label>
        <label>Reason<input name="reason" required maxLength="240" /></label>
        <button disabled={busy}>Record correction</button>{problem(`/api/v1/commerce/sales/${s.id}/notes/`,'Could not record the correction.')}</form></details>}
      {s.status==='COMPLETED'&&canCorrect&&<details><summary>Return all goods and refund received payments</summary><p>Confirm that every item has physically returned. Service sales require separate review.</p><form onSubmit={e=>submit(e,`/api/v1/commerce/sales/${s.id}/return/`,{},`${s.number} returned and refunded.`)}><label>Reason<input name="reason" required maxLength="240" /></label><label><input type="checkbox" required />Goods returned and refund completed</label><button disabled={busy}>Record full return</button>{problem(`/api/v1/commerce/sales/${s.id}/return/`,'Could not record the full return.')}</form></details>}
    </section></details>{notice?.saleId===s.id&&<FormSuccess message={notice.text} />}</Fragment>;})}</>}{explainItem&&<ExplainProfitPanel itemId={explainItem} onClose={()=>setExplainItem(null)} />}{receiptSale&&<ReceiptPanel saleId={receiptSale} onClose={()=>setReceiptSale(null)} />}
    <nav className="pager" aria-label="Sales pages"><button disabled={page===1} onClick={()=>setPage(p=>p-1)}>Previous</button><span> Page {page}{data?.count?` of ${Math.max(1,Math.ceil(data.count/50))}`:''} </span><button disabled={!data||page*50>=data.count} onClick={()=>setPage(p=>p+1)}>Next</button></nav>
  </>;
}
