import { useEffect, useState } from 'react';
import { checkHealth } from '../api/pipeline';

type Status = 'checking' | 'ok' | 'error';

export function HealthStatus() {
  const [status, setStatus] = useState<Status>('checking');
  const [label, setLabel] = useState('Checking service…');

  useEffect(() => {
    checkHealth()
      .then((data) => {
        setStatus('ok');
        setLabel(`${data.service} v${data.version} — service OK`);
      })
      .catch((err: Error) => {
        setStatus('error');
        setLabel(`Service unreachable: ${err.message}`);
      });
  }, []);

  return (
    <section className="card health-card">
      <div className="status-row">
        <span className={`status-dot ${status === 'checking' ? '' : status}`} />
        <span>{label}</span>
      </div>
    </section>
  );
}
