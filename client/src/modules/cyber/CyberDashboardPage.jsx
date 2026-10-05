import { businessCurrency } from "../../core/organization/presentation";
import { MetricCard } from "../../components/dashboard/MetricCard";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Empty, ErrorState, Loading } from "../../components/States";
import { useAuth } from "../../core/auth/AuthContext";
import { FormField } from "../../components/forms/FormField";
import { FormError } from "../../components/forms/FormNotice";
import {
  completeCyberJob,
  createCyberService,
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
import { askForm, confirmAction, showError } from "../../core/ui/alerts";
import { label, PAYMENT_METHODS } from "../../core/ui/labels";
import { ReceiptPanel } from "../receipts/ReceiptPanel";
import { useLiveRefresh } from "../../core/data/liveRefresh";
const billingUnits = ["PER_PAGE", "PER_COPY", "PER_SHEET", "PER_DOCUMENT", "PER_HOUR", "PER_ITEM", "FIXED"];
export function CyberDashboardPage() {
  const { user } = useAuth();
  const canManageServices = Boolean(user?.permissions?.includes("cyber.add_cyberserviceprofile") && user?.permissions?.includes("catalog.add_product"));
  const canChangeServices = Boolean(user?.permissions?.includes("cyber.change_cyberserviceprofile"));
  const canDeleteJobs = Boolean(user?.permissions?.includes("cyber.delete_cyberjob"));
  const canDeleteSales = Boolean(user?.permissions?.includes("commerce.change_sale"));
  const [serviceError, setServiceError] = useState(null);
  const [dashboard, setDashboard] = useState();
  const [jobs, setJobs] = useState([]);
  const [services, setServices] = useState([]);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState("");
  const [receiptSale, setReceiptSale] = useState(null);
  const [showReceipt, setShowReceipt] = useState(false);
  const load = async () => {
    try {
      const [summary, jobRows, serviceRows] = await Promise.all([
        getCyberDashboard(),
        getCyberJobs(),
        getCyberServices(),
      ]);
      setDashboard(summary);
      setJobs(jobRows);
      setServices(serviceRows);
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
  const addService = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setServiceError(null);
    try {
      await createCyberService({
        name: values.get("name"),
        selling_price: values.get("selling_price"),
        billing_unit: values.get("billing_unit"),
        requires_job: values.get("requires_job") === "on",
        notes: values.get("notes") || "",
      });
      form.reset();
      await load();
    } catch (err) {
      setServiceError({ place: "add", title: "Could not add the service.", message: err.message });
    }
  };
  const toggleService = async (service) => {
    setServiceError(null);
    try {
      await updateCyberService(service.id, { active: !service.active });
      await load();
    } catch (err) {
      setServiceError({ place: "list", title: `Could not update ${service.name}.`, message: err.message });
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
  const complete = async (job) => {
    const paid = await askForm({
      title: `Complete job ${job.number}?`,
      text: "This records the payment and marks the job as completed.",
      confirmButtonText: "Pay & complete",
      fields: [
        { name: "method", label: "Paid by", type: "select", options: PAYMENT_METHODS, value: "CASH", required: true },
        { name: "reference", label: "Payment reference, e.g. the M-Pesa code", placeholder: "e.g. SJK4H7T2QX" },
      ],
    });
    if (!paid) return;
    try {
      const result = await completeCyberJob(job.id, {
        payment_method: paid.method,
        payment_reference: paid.reference,
        idempotency_key: `cyber:${job.number}`,
      });
      setReceipt(`${result.receipt_number} · ${businessCurrency()} ${result.total} · ${label(paid.method)}`);
      setReceiptSale(result.sale_id);
      await load();
    } catch (err) {
      await showError(`Could not complete job ${job.number}.`, err.message);
    }
  };
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
      <div className="metrics">
        <MetricCard label="Today's revenue">
          {businessCurrency()} {dashboard.today.revenue}
        </MetricCard>
        <MetricCard label="Active jobs">{dashboard.active_jobs}</MetricCard>
        <MetricCard label="Ready">{dashboard.ready_jobs}</MetricCard>
        <MetricCard label="Completed today">{dashboard.today.jobs}</MetricCard>
        <MetricCard label="Average job">
          {businessCurrency()} {dashboard.today.average}
        </MetricCard>
      </div>
      <div className="deskGrid">
        <CyberJobForm
          services={services.filter((service) => service.active)}
          onSave={async (data) => {
            const job = await createCyberJob(data);
            await load();
            return job;
          }}
        />
        <section>
          <h2>Active & ready jobs</h2>
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
                        <button onClick={() => void complete(job)}>
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
      <section>
        <h2>Service price list</h2>
        {!services.length && <Empty>No services yet.{canManageServices ? " Add your first service below." : " Ask the business owner to add services."}</Empty>}
        <div className="serviceGrid">
          {services.map((service) => (
            <article key={service.id}>
              <b>{service.name}</b>
              <strong>{businessCurrency()} {service.selling_price}</strong>
              <small>
                {service.billing_unit.replaceAll("_", " ")}
                {service.requires_job ? " · Job workflow" : " · Quick service"}
                {!service.active && " · Inactive"}
              </small>
              {canChangeServices && service.product && (
                <Link className="button secondary" to={`/admin/cyber/income/${service.product}`} aria-label={`Edit ${service.name}`}>Edit</Link>
              )}
              {canChangeServices && (
                <button type="button" className="secondary" onClick={() => void toggleService(service)}>
                  {service.active ? "Deactivate" : "Activate"}
                </button>
              )}
            </article>
          ))}
        </div>
        {serviceError?.place === "list" && <FormError title={serviceError.title} message={serviceError.message} />}
        {canManageServices && (
          <form className="formCard" onSubmit={(event) => void addService(event)}>
            <h3>Add a service</h3>
            <FormField label="Service name" name="name" required maxLength={180} placeholder="e.g. Black & white printing" />
            <FormField label={`Price (${businessCurrency()})`} name="selling_price" type="number" min="0" step="0.01" required />
            <label>
              Charged
              <select name="billing_unit" defaultValue="PER_PAGE">
                {billingUnits.map((unit) => <option key={unit} value={unit}>{unit.replaceAll("_", " ").toLowerCase()}</option>)}
              </select>
            </label>
            <label className="checkRow"><input type="checkbox" name="requires_job" /> Track as a job (for work that takes time, like typing or repairs)</label>
            <FormField label="Notes (optional)" name="notes" />
            <button>Add service</button>
            {serviceError?.place === "add" && <FormError title={serviceError.title} message={serviceError.message} />}
          </form>
        )}
      </section>
    </>
  );
}
