import { MetricCard } from "../../components/dashboard/MetricCard";
import { useEffect, useState } from "react";
import { Empty, ErrorState, Loading } from "../../components/States";
import {
  completeCyberJob,
  createCyberJob,
  getCyberDashboard,
  getCyberJobs,
  getCyberServices,
  transitionCyberJob,
} from "./api";
import { CyberJobForm } from "./CyberJobForm";
import { confirmAction } from "../../core/ui/alerts";
export function CyberDashboardPage() {
  const [dashboard, setDashboard] = useState();
  const [jobs, setJobs] = useState([]);
  const [services, setServices] = useState([]);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState("");
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
  if (error) return <ErrorState message={error} retry={load} />;
  if (!dashboard) return <Loading />;
  const complete = async (job) => {
    if (
      !(await confirmAction({
        title: `Complete job ${job.number}?`,
        text: "This records payment and marks the job as completed.",
        confirmButtonText: "Pay & complete",
      }))
    )
      return;
    const method =
      window.prompt("Payment method: CASH, MPESA, BANK or OTHER", "CASH") ||
      "CASH";
    const reference = window.prompt("Payment reference (optional)", "") || "";
    const result = await completeCyberJob(job.id, {
      payment_method: method.toUpperCase(),
      payment_reference: reference,
      idempotency_key: `cyber:${job.number}`,
    });
    setReceipt(
      `${result.receipt_number} · KSh ${result.total} · ${method.toUpperCase()}`,
    );
    await load();
  };
  return (
    <>
      <span className="eyebrow">Cyber operations</span>
      <h1>Cyber Desk</h1>
      <p className="privacyNotice">
        Store operational metadata only. Never record customer passwords, PINs,
        OTPs, or document contents.
      </p>
      {receipt && (
        <div className="success">
          <b>Cyber receipt: {receipt}</b>
          <button onClick={() => window.print()}>Print receipt</button>
        </div>
      )}
      <div className="metrics">
        <MetricCard label="Today's revenue">
          KSh {dashboard.today.revenue}
        </MetricCard>
        <MetricCard label="Active jobs">{dashboard.active_jobs}</MetricCard>
        <MetricCard label="Ready">{dashboard.ready_jobs}</MetricCard>
        <MetricCard label="Completed today">{dashboard.today.jobs}</MetricCard>
        <MetricCard label="Average job">
          KSh {dashboard.today.average}
        </MetricCard>
      </div>
      <div className="deskGrid">
        <CyberJobForm
          services={services}
          onSave={async (data) => {
            await createCyberJob(data);
            await load();
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
                      {job.status} · KSh {job.total}
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
                          await transitionCyberJob(job.id, "IN_PROGRESS");
                          await load();
                        }}
                      >
                        Start
                      </button>
                    )}
                    {job.status !== "READY" &&
                      !["COMPLETED", "CANCELLED"].includes(job.status) && (
                        <button
                          onClick={async () => {
                            if (
                              !(await confirmAction({
                                title: `Mark ${job.number} ready?`,
                                text: "The customer will be able to collect this job.",
                                confirmButtonText: "Mark ready",
                              }))
                            )
                              return;
                            await transitionCyberJob(job.id, "READY");
                            await load();
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
        <div className="serviceGrid">
          {services.map((service) => (
            <article key={service.id}>
              <b>{service.name}</b>
              <strong>KSh {service.selling_price}</strong>
              <small>
                {service.billing_unit.replaceAll("_", " ")}
                {service.requires_job ? " · Job workflow" : " · Quick service"}
              </small>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
