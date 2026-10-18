// Admin > Jobs: every scheduled job, when it last ran, how long it took, whether it worked, and when it runs
// next. Owner only, read only — nothing here can start or change a job. Times are India time (IST).

import { useQuery } from '@tanstack/react-query'

import { api } from '../../api/client'
import { countFailed, formatDuration, formatIST, formatNext, jobState } from '../jobs'
import { Card, PageHead, Tag } from '../ui'

export default function Jobs() {
  const q = useQuery({ queryKey: ['admin-jobs'], queryFn: api.adminJobs, refetchInterval: 30_000 })
  const data = q.data
  const now = data ? Date.parse(data.generated_at) : Date.now()
  const failed = data ? countFailed(data.jobs) : 0

  return (
    <div className="tm-page tm-grid">
      <PageHead
        title="Jobs"
        sub="Everything the bot does on a timer. All times are India time (IST). Refreshes every 30 seconds."
      />

      {q.isLoading && <p className="tm-dim">Loading…</p>}
      {q.isError && <p className="tm-neg">Could not load the job list. Try again shortly.</p>}

      {data && (
        <>
          {!data.worker_alive && (
            <Card glow title="The background worker is not answering">
              <p className="tm-neg" style={{ margin: 0 }}>
                No heartbeat for over 3 minutes. Jobs are probably not running; the list below is the last one the
                worker sent.
              </p>
            </Card>
          )}
          {!data.runs_available && (
            <p className="tm-neg" data-testid="jobs-runs-missing">
              Could not read the last-run records (Redis did not answer). Schedules and next runs are still shown.
            </p>
          )}

          <Card
            title={`${data.jobs.length} scheduled jobs`}
            sub={failed ? `${failed} failed on their last run.` : 'None failed on their last run.'}
          >
            {data.jobs.length === 0 ? (
              <p className="tm-dim">The worker has not sent its job list yet.</p>
            ) : (
              <div className="tm-table-wrap" tabIndex={0} role="region" aria-label="Table, scroll sideways to see more">
                <table className="tm-table" data-testid="jobs-table">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Schedule</th>
                      <th>Last run started</th>
                      <th>Took</th>
                      <th>Result</th>
                      <th>Next run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs.map((j) => {
                      const st = jobState(j)
                      return (
                        <tr key={j.id} data-job={j.id}>
                          <td className="tm-wrap">
                            <div className="tm-strong">{j.name}</div>
                            {j.about && <div className="tm-dim">{j.about}</div>}
                          </td>
                          <td className="tm-wrap">{j.registered ? j.schedule ?? '—' : 'No longer scheduled'}</td>
                          <td>{formatIST(j.last_started_at)}</td>
                          <td>{formatDuration(j.last_duration_s)}</td>
                          <td className="tm-wrap">
                            <Tag tone={st.tone}>{st.label}</Tag>
                            {st.detail && <div className="tm-dim">{st.detail}</div>}
                          </td>
                          <td>{j.registered ? formatNext(j.next_run, now) : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="tm-dim" style={{ marginBottom: 0 }}>
              "Not run yet" means no run has been recorded since run tracking was added. "Failed" shows only the kind
              of error; the full message is in the worker log and the Telegram alert.
            </p>
          </Card>
        </>
      )}
    </div>
  )
}
