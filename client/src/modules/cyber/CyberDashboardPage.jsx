import { businessCurrency } from "../../core/organization/presentation";
import { MetricCard } from "../../components/dashboard/MetricCard";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorState, Loading } from "../../components/States";
import { useAuth } from "../../core/auth/AuthContext";
import { FormError } from "../../components/forms/FormNotice";
import {
  updateCyberService,
  createCyberJob,
  deleteCyberJob,
  deleteCyberSale,
  getCyberDashboard,
  getCyberJobs,
  getCyberServices,
  transitionCyberJob,
} from "./api";
import { CyberJobForm } from "./CyberJobForm";
import { CyberAnalysis } from "./CyberAnalysis";
import { NewService, RecordIncome } from "./CyberIncomePage";
import { api } from "../../core/api/client";
import { askForm, confirmAction, showError } from "../../core/ui/alerts";
import { label } from "../../core/ui/labels";
import { CustomerChooser, useCustomers } from "../pos/CustomerChooser";
import { CyberPay, useOpenCyberCheckout } from "./CyberPay";
import { ReceiptPanel } from "../receipts/ReceiptPanel";
import { useLiveRefresh } from "../../core/data/liveRefresh";
import { PartBooks } from "../admin/PartBooks";
// A done job charged and paid at the same checkout as the till: first who pays (a named customer can owe part of it),
// then cash, M-Pesa, bank, a mix, or owed.
function JobPayment({ user, job, checkout, setCheckout, onPaid, onClose }) {
  const [customers, setCustomers] = useCustomers(user);
  const [customerId, setCustomerId] = useState(job?.customer ? String(job.customer) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const charge = async () => {
    setBusy(true);
    setError("");
    try {
      setCheckout(await api(`/api/v1/cyber/jobs/${job.id}/checkout/`, { method: "POST",
        body: JSON.stringify({ idempotency_key: crypto.randomUUID(), ...(customerId ? { customer_id: customerId } : {}) }) }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="formCard incomeEntry" aria-label="Pay for the job">
      <h2>Pay &amp; complete {job?.number || ""}</h2>
      {checkout ? <CyberPay checkout={checkout} customers={customers} onChange={setCheckout} onDone={onPaid}
        onBack={() => { setCheckout(null); onClose(); }} /> : <>
        <p className="muted">{job.walk_in_customer_name || "Walk-in"} · {businessCurrency()} {job.total}</p>
        <CustomerChooser user={user} customers={customers} setCustomers={setCustomers} value={customerId} onChange={setCustomerId} />
        <div className="actionRow">
          <button type="button" disabled={busy} onClick={() => void charge()}>{busy ? "Charging…" : `Charge ${businessCurrency()} ${job.total}`}</button>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
        </div>
        <FormError title={`Could not charge job ${job.number}.`} message={error} />
      </>}
    </section>
  );
}

export function CyberDashboardPage() {
  const { user } = useAuth();
  const canManageServices = Boolean(user?.permissions?.includes("cyber.add_cyberserviceprofile") && user?.permissions?.includes("catalog.add_product"));
  const canChangeServices = Boolean(user?.permissions?.includes("cyber.change_cyberserviceprofile"));
  const canDeleteJobs = Boolean(user?.permissions?.includes("cyber.delete_cyberjob"));
  const canDeleteSales = Boolean(user?.permissions?.includes("commerce.change_sale"));
  const canDeleteServices = Boolean(user?.permissions?.includes("cyber.delete_cyberserviceprofile"));
  const [serviceError, setServiceError] = useState(null);
  const [dashboard, setDashboard] = useState();
  const [jobs, setJobs] = useState([]);
  const [services, setServices] = useState([]);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState("");
  const [receiptSale, setReceiptSale] = useState(null);
  const [showReceipt, setShowReceipt] = useState(false);
  const [takingJob, setTakingJob] = useState(false);
  const [income, setIncome] = useState({ services: [], groups: [] });
  const [addingService, setAddingService] = useState(false);
  // The job being paid for, and its checkout once charged (picked up again after a reload).
  const [paying, setPaying] = useState(null);
  const [jobCheckout, setJobCheckout] = useOpenCyberCheckout(user, (row) => Boolean(row.job_id));
  const load = async () => {
    try {
      const [summary, jobRows, serviceRows, incomeRows] = await Promise.all([
        getCyberDashboard(),
        getCyberJobs(),
        getCyberServices(),
        api("/api/v1/cyber/income/").catch(() => ({ services: [], groups: [] })),
      ]);
      setDashboard(summary);
      setJobs(jobRows);
      setServices(serviceRows);
      setIncome(incomeRows || { services: [], groups: [] });
    } catch (err) {
      setError(err.message);
    }
  };
  useEffect(() => {
    void load();
  }, []);
  useLiveRefresh(load);
  if (error) return <ErrorState message={error} retry={load} />;
  if (!dashboard) return <Loading />;
  // Hide or show again every price option of a service (a hidden service cannot be chosen when recording).
  const toggleService = async (service) => {
    setServiceError(null);
    try {
      for (const profile of services.filter((row) => row.product === service.id)) await updateCyberService(profile.id, { active: !service.active });
      await load();
    } catch (err) {
      setServiceError({ place: "list", title: `Could not update ${service.name}.`, message: err.message });
    }
  };
  const removeService = async (service) => {
    if (!(await confirmAction({ title: `Delete ${service.name}?`, confirmButtonText: "Delete service",
      text: "It disappears from your services and can no longer be recorded. Money already recorded for it is kept in your totals." }))) return;
    setServiceError(null);
    try {
      await api(`/api/v1/cyber/income/${service.id}/delete/`, { method: "POST" });
      await load();
    } catch (err) {
      setServiceError({ place: "list", title: `Could not delete ${service.name}.`, message: err.message });
    }
  };
  // A job action that fails says so instead of silently doing nothing.
  const act = async (failure, work) => {
    try {
      await work();
      await load();
    } catch (err) {
      await showError(failure, err.message);
    }
  };
  const paid = async (result) => {
    setJobCheckout(null);
    setPaying(null);
    setReceipt(`${result.receipt.receipt_number} · ${businessCurrency()} ${result.receipt.total}`);
    setReceiptSale(result.receipt.sale_id);
    await load();
  };
  const payingJob = paying || (jobCheckout && (jobs.find((job) => job.id === jobCheckout.job_id) || { id: jobCheckout.job_id, number: "", total: jobCheckout.total }));
  return (
    <>
      <span className="eyebrow">{user?.organization?.business_type || "Services"}</span>
      <h1>Service Desk</h1>
      <p className="privacyNotice">
        Store operational metadata only. Never record customer passwords, PINs,
        OTPs, or document contents.
      </p>
      {receipt && (
        <div className="success">
          <b>Cyber receipt: {receipt}</b>
          {receiptSale && <button onClick={() => setShowReceipt(true)}>View &amp; send receipt</button>}
        </div>
      )}
      {showReceipt && receiptSale && <ReceiptPanel saleId={receiptSale} onClose={() => setShowReceipt(false)} />}
      {payingJob && <JobPayment user={user} job={payingJob} checkout={jobCheckout} setCheckout={setJobCheckout} onPaid={paid}
        onClose={() => setPaying(null)} />}
      <div className="metrics">
        <MetricCard label="Revenue since the start">
          {businessCurrency()} {dashboard.all_time?.revenue ?? 0}
        </MetricCard>
        <MetricCard label="Active jobs">{dashboard.active_jobs}</MetricCard>
        <MetricCard label="Ready">{dashboard.ready_jobs}</MetricCard>
        <MetricCard label="Completed today">{dashboard.today.jobs}</MetricCard>
        <MetricCard label="Average job">
          {businessCurrency()} {Number(dashboard.all_time?.average || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </MetricCard>
      </div>
      <div className="deskGrid">
        <RecordIncome services={income.services || []} groups={income.groups || []} onSaved={load} onServicesChanged={load}
          title="Record a service done" />
        <section>
          <div className="sectionHeading">
            <h2>Jobs</h2>
            {!takingJob && <button type="button" className="secondary" onClick={() => setTakingJob(true)}>+ Take in a job for later</button>}
          </div>
          {takingJob && <>
            <CyberJobForm
              services={services.filter((service) => service.active)}
              onSave={async (data) => {
                const job = await createCyberJob(data);
                await load();
                return job;
              }}
            />
            <button type="button" className="secondary" onClick={() => setTakingJob(false)}>Close</button>
          </>}
          {!jobs.length ? (
            <Empty>No Cyber jobs yet.</Empty>
          ) : (
            <div className="list">
              {jobs.slice(0, 20).map((job) => (
                <article key={job.id}>
                  <div>
                    <b>
                      {job.number} · {job.walk_in_customer_name || "Walk-in"}
                    </b>
                    <small>
                      {label(job.status)} · {businessCurrency()} {job.total}
                    </small>
                    {job.lines.map((line) => (
                      <span key={line.id}>
                        {line.service_name} × {line.quantity}
                      </span>
                    ))}
                  </div>
                  <div className="jobActions">
                    {job.status === "QUEUED" && (
                      <button
                        onClick={async () => {
                          if (
                            !(await confirmAction({
                              title: `Start job ${job.number}?`,
                              text: "This moves the job into active work.",
                              confirmButtonText: "Start job",
                              icon: "question",
                            }))
                          )
                            return;
                          await act(`Could not start job ${job.number}.`, () => transitionCyberJob(job.id, "IN_PROGRESS"));
                        }}
                      >
                        Start
                      </button>
                    )}
                    {canDeleteJobs && job.status === "QUEUED" && !job.started_at && !job.sale && (
                      <button
                        type="button"
                        className="danger"
                        aria-label={`Delete job ${job.number}`}
                        onClick={async () => {
                          if (
                            !(await confirmAction({
                              title: `Delete job ${job.number}?`,
                              text: "The job is removed completely. Nothing was started or paid for it, so no money or stock is affected.",
                              confirmButtonText: "Delete job",
                            }))
                          )
                            return;
                          await act(`Could not delete job ${job.number}.`, () => deleteCyberJob(job.id));
                        }}
                      >
                        Delete
                      </button>
                    )}
                    {canDeleteSales && job.status === "COMPLETED" && job.sale && (
                      <button
                        type="button"
                        className="danger"
                        aria-label={`Delete paid job ${job.number}`}
                        onClick={async () => {
                          const values = await askForm({
                            title: `Delete ${job.number}?`,
                            text: "Use this when it was recorded wrongly. Its money and payment come out of that day's figures and it disappears from the desk, sales and income. Record it again correctly afterwards.",
                            confirmButtonText: "Delete",
                            fields: [{ name: "reason", label: "Reason", required: true, placeholder: "e.g. recorded wrongly, will record again" }],
                          });
                          if (!values) return;
                          await act(`Could not delete ${job.number}.`, () => deleteCyberSale(job.sale, values.reason));
                        }}
                      >
                        Delete
                      </button>
                    )}
                    {job.status !== "READY" &&
                      !["COMPLETED", "CANCELLED"].includes(job.status) && (
                        <button
                          onClick={async () => {
                            if (
                              !(await confirmAction({
                                title: `Mark ${job.number} ready?`,
                                text: "The walk-in customer can collect this completed job.",
                                confirmButtonText: "Mark ready",
                              }))
                            )
                              return;
                            await act(`Could not mark ${job.number} ready.`, () => transitionCyberJob(job.id, "READY"));
                          }}
                        >
                          Ready
                        </button>
                      )}
                    {job.status !== "COMPLETED" &&
                      job.status !== "CANCELLED" && (
                        <button onClick={() => { setPaying(job); window.scrollTo?.({ top: 0, behavior: "smooth" }); }} disabled={Boolean(payingJob)}>
                          Pay & complete
                        </button>
                      )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
      <section aria-labelledby="your-services">
        <div className="sectionHeading">
          <h2 id="your-services">Your services</h2>
          {canManageServices && !addingService && <button type="button" onClick={() => setAddingService(true)}>+ Create a new service</button>}
        </div>
        {canManageServices && addingService && <NewService groups={income.groups || []} startOpen
          onSaved={async () => { setAddingService(false); await load(); }} onCancel={() => setAddingService(false)} />}
        {!(income.services || []).length && <Empty>No services yet.{canManageServices ? " Create your first service." : " Ask the business owner to add services."}</Empty>}
        <div className="serviceGrid">
          {(income.services || []).map((service) => (
            <article key={service.id} className={service.active ? undefined : "muted"}>
              <b>{service.name}</b>
              <small>{service.options.filter((o) => o.active).map((o) => `${service.options.length > 1 ? `${o.name}: ` : ""}${o.price_varies || Number(o.price) <= 0 ? "amount varies" : `${businessCurrency()} ${Number(o.price).toLocaleString()}${o.billing_unit === "FIXED" ? "" : ` per ${o.billing_unit.replace("PER_", "").toLowerCase()}`}`}`).join(" · ")}
                {!service.active && " · Hidden"}</small>
              <div className="actionRow">
                {canChangeServices && <Link className="button secondary" to={`/admin/cyber/income/${service.id}`} aria-label={`Edit ${service.name}`}>Edit</Link>}
                {canChangeServices && <button type="button" className="secondary" onClick={() => void toggleService(service)}>{service.active ? "Hide" : "Show again"}</button>}
                {canDeleteServices && <button type="button" className="danger" aria-label={`Delete ${service.name}`} onClick={() => void removeService(service)}>Delete</button>}
              </div>
            </article>
          ))}
        </div>
        {serviceError?.place === "list" && <FormError title={serviceError.title} message={serviceError.message} />}
      </section>
      <PartBooks part="CYBER" refreshKey={dashboard.today.jobs} />
      <CyberAnalysis refreshKey={dashboard.today.jobs} />
    </>
  );
}
