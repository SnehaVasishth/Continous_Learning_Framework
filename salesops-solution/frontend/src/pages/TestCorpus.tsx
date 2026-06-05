// === v1.1 TASK-7 START ===
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  testCorpusApi,
  type TestCase,
  type TestRun,
  type TestRunResult,
} from "../api";
import { Button, PageHeader, Section, Surface } from "../components/ui";

export function TestCorpusPage() {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [selectedRun, setSelectedRun] = useState<TestRun | null>(null);
  const [results, setResults] = useState<TestRunResult[]>([]);
  const [running, setRunning] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [cs, rs] = await Promise.all([
        testCorpusApi.listCases(),
        testCorpusApi.listRuns(),
      ]);
      setCases(cs);
      setRuns(rs);
      if (rs.length > 0 && !selectedRun) {
        const latest = rs[0];
        setSelectedRun(latest);
        const det = await testCorpusApi.getRunResults(latest.id);
        setResults(det.results);
      }
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const onSelectRun = async (r: TestRun) => {
    setSelectedRun(r);
    try {
      const det = await testCorpusApi.getRunResults(r.id);
      setResults(det.results);
    } catch (e) {
      setErrMsg(String(e));
    }
  };

  const onRun = async () => {
    setRunning(true);
    setErrMsg(null);
    try {
      const newRun = await testCorpusApi.triggerRun(
        `manual run ${new Date().toLocaleString()}`,
      );
      await refresh();
      setSelectedRun(newRun);
      const det = await testCorpusApi.getRunResults(newRun.id);
      setResults(det.results);
    } catch (e) {
      setErrMsg(String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Test Corpus: labelled regression suite"
        subtitle={
          <>
            Synthetic emails with expected intent labels. Run the corpus end to end through the live case-processing flow,
            see the prior Keysight POC's accuracy report format (Initial Pass / Failed / Post-Fix Pass / Still Failed).
          </>
        }
      />

      {errMsg && (
        <Surface>
          <div className="p-4 text-sm text-amber-800 dark:text-amber-300">{errMsg}</div>
        </Surface>
      )}

      <Surface>
        <Section
          title="Corpus runs"
          action={
            <div className="flex items-center gap-2">
              <Button onClick={refresh} variant="ghost">Refresh</Button>
              <Button onClick={onRun} variant="primary" disabled={running}>
                {running ? "Running…" : `Run corpus (${cases.length} cases)`}
              </Button>
            </div>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-zbrain-muted dark:text-zbrain-dark-muted border-b border-zbrain-divider/70 dark:border-zbrain-dark-divider/60">
                  <th className="py-2 pr-3">Run</th>
                  <th className="py-2 pr-3">Cases</th>
                  <th className="py-2 pr-3">Initial pass</th>
                  <th className="py-2 pr-3">Failed</th>
                  <th className="py-2 pr-3">Pass %</th>
                  <th className="py-2 pr-3">Started</th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-zbrain-muted dark:text-zbrain-dark-muted">
                      No runs yet. Add some cases below and click "Run corpus".
                    </td>
                  </tr>
                )}
                {runs.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => onSelectRun(r)}
                    className={
                      "cursor-pointer hover:bg-zbrain-50 dark:hover:bg-zbrain-dark-elev2 " +
                      (selectedRun?.id === r.id
                        ? "bg-zbrain-50 dark:bg-zbrain-dark-elev2"
                        : "")
                    }
                  >
                    <td className="py-2 pr-3 font-mono text-xs">#{r.id} · {r.label}</td>
                    <td className="py-2 pr-3 tabular-nums">{r.case_count}</td>
                    <td className="py-2 pr-3 tabular-nums text-emerald-700 dark:text-emerald-400">
                      {r.initial_pass}
                    </td>
                    <td className="py-2 pr-3 tabular-nums text-amber-700 dark:text-amber-400">
                      {r.initial_fail}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">
                      {r.pass_pct === null ? "-" : `${r.pass_pct.toFixed(1)}%`}
                    </td>
                    <td className="py-2 pr-3 text-zbrain-muted dark:text-zbrain-dark-muted">
                      {r.started_at ? new Date(r.started_at).toLocaleString() : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </Surface>

      {selectedRun && (
        <Surface>
          <Section title={`Run #${selectedRun.id} results`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-zbrain-muted dark:text-zbrain-dark-muted border-b border-zbrain-divider/70 dark:border-zbrain-dark-divider/60">
                    <th className="py-2 pr-3">Case</th>
                    <th className="py-2 pr-3">Expected</th>
                    <th className="py-2 pr-3">Actual</th>
                    <th className="py-2 pr-3">Result</th>
                    <th className="py-2 pr-3">Pipeline</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.id} className="border-b border-zbrain-divider/40 dark:border-zbrain-dark-divider/40">
                      <td className="py-2 pr-3">
                        <div className="font-medium text-zbrain-ink dark:text-zbrain-dark-ink">
                          {r.case_name}
                        </div>
                        <div className="text-xs text-zbrain-muted dark:text-zbrain-dark-muted">
                          {r.case_subject}
                        </div>
                      </td>
                      <td className="py-2 pr-3 font-mono text-xs">{r.expected_intent}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{r.actual_intent ?? "-"}</td>
                      <td className="py-2 pr-3">
                        {r.pass_initial ? (
                          <span className="pill bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300 border border-emerald-200/70 dark:border-emerald-500/30">
                            PASS
                          </span>
                        ) : (
                          <span className="pill bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300 border border-amber-200/70 dark:border-amber-500/30">
                            FAIL
                          </span>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-zbrain-muted dark:text-zbrain-dark-muted">
                        {r.pipeline_id ? (
                          <Link className="underline" to={`/trace/${r.pipeline_id}`}>
                            #{r.pipeline_id}
                          </Link>
                        ) : (
                          "-"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        </Surface>
      )}

      <Surface>
        <Section
          title="Test cases"
          action={
            <Button onClick={() => setShowAdd((v) => !v)} variant="ghost">
              {showAdd ? "Cancel" : "Add case"}
            </Button>
          }
        >
          {showAdd && <AddCaseForm onAdded={refresh} onClose={() => setShowAdd(false)} />}
          <div className="overflow-x-auto mt-3">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-zbrain-muted dark:text-zbrain-dark-muted border-b border-zbrain-divider/70 dark:border-zbrain-dark-divider/60">
                  <th className="py-2 pr-3">Name</th>
                  <th className="py-2 pr-3">From</th>
                  <th className="py-2 pr-3">Subject</th>
                  <th className="py-2 pr-3">Expected intent</th>
                </tr>
              </thead>
              <tbody>
                {cases.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-zbrain-muted dark:text-zbrain-dark-muted">
                      No cases yet. Click "Add case".
                    </td>
                  </tr>
                )}
                {cases.map((c) => (
                  <tr key={c.id} className="border-b border-zbrain-divider/40 dark:border-zbrain-dark-divider/40">
                    <td className="py-2 pr-3 font-medium">{c.name}</td>
                    <td className="py-2 pr-3 text-zbrain-muted dark:text-zbrain-dark-muted">{c.from_address}</td>
                    <td className="py-2 pr-3">{c.subject}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{c.expected_intent}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </Surface>
    </div>
  );
}

function AddCaseForm({ onAdded, onClose }: { onAdded: () => void; onClose: () => void }) {
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [fromAddr, setFromAddr] = useState("");
  const [body, setBody] = useState("");
  const [expectedIntent, setExpectedIntent] = useState("po_intake");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await testCorpusApi.addCase({
        name,
        subject,
        from_address: fromAddr,
        body,
        expected_intent: expectedIntent,
        expected_action: null,
        expected_routing: null,
        expected_keywords: [],
        notes: null,
      });
      setName("");
      setSubject("");
      setFromAddr("");
      setBody("");
      onAdded();
      onClose();
    } finally {
      setBusy(false);
    }
  };

  const inp =
    "w-full px-3 py-2 rounded-md border border-zbrain-divider dark:border-zbrain-dark-divider bg-white dark:bg-zbrain-dark-elev1 text-sm";

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
      <input className={inp} placeholder="case name (e.g. po_aurora)" value={name} onChange={(e) => setName(e.target.value)} />
      <input className={inp} placeholder="from address" value={fromAddr} onChange={(e) => setFromAddr(e.target.value)} />
      <input className={inp + " md:col-span-2"} placeholder="subject" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <textarea className={inp + " md:col-span-2"} rows={5} placeholder="body" value={body} onChange={(e) => setBody(e.target.value)} />
      <input className={inp} placeholder="expected_intent (e.g. po_intake)" value={expectedIntent} onChange={(e) => setExpectedIntent(e.target.value)} />
      <div className="flex items-center justify-end gap-2">
        <Button onClick={submit} variant="primary" disabled={busy}>
          {busy ? "Adding…" : "Add"}
        </Button>
      </div>
    </div>
  );
}
// === v1.1 TASK-7 END ===
