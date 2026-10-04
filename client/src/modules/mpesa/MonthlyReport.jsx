import { useEffect, useState } from "react";
import { FormError } from "../../components/forms/FormNotice";
import { downloadMpesaReport, getMpesaReportMonths } from "./api";

function save(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// Once a month has ended (from the 1st), its report appears here ready to download as a PDF: every day's
// deposits, withdrawals, float top-ups and money in operation. Earlier months stay available below it.
export function MonthlyReport() {
  const [months, setMonths] = useState([]);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    // Owners and managers only; for anyone else the server refuses and nothing is shown.
    getMpesaReportMonths().then(setMonths).catch(() => setMonths([]));
  }, []);
  if (!months.length) return null;
  const [latest, ...earlier] = months;
  const download = async (month) => {
    setBusy(month);
    setError("");
    try {
      save(await downloadMpesaReport(month), `mpesa-report-${month}.pdf`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="monthlyReport" aria-labelledby="monthly-report-heading">
      <h2 id="monthly-report-heading">Monthly report</h2>
      <div className="monthlyReportReady">
        <p><strong>{latest.label}</strong> has ended. Its full report is ready: every day's deposits, withdrawals, float top-ups
          and money in operation, with times.</p>
        <button type="button" disabled={Boolean(busy)} onClick={() => void download(latest.month)}>
          {busy === latest.month ? "Preparing PDF…" : `Download ${latest.label} report (PDF)`}
        </button>
      </div>
      {earlier.length > 0 && (
        <div className="actionRow monthlyReportEarlier">
          <label>Earlier month
            <select value={picked} onChange={(event) => setPicked(event.target.value)}>
              <option value="">Choose a month</option>
              {earlier.map((month) => <option key={month.month} value={month.month}>{month.label}</option>)}
            </select>
          </label>
          <button type="button" className="secondary" disabled={!picked || Boolean(busy)} onClick={() => void download(picked)}>
            {busy && busy === picked ? "Preparing PDF…" : "Download PDF"}
          </button>
        </div>
      )}
      <p className="muted">The PDF lists customers' phone and ID numbers. Keep it somewhere safe, such as a backed-up folder only you can open.</p>
      <FormError title="Could not download the report." message={error} />
    </section>
  );
}
