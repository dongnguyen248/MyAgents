export interface Series {
  name: string;
  values: number[];
  color: string; // CSS colour or var(--sN)
}

interface Props {
  kind: 'bar' | 'line';
  labels: string[];
  series: Series[];
  format?: (v: number) => string;
  title: string;
  height?: number;
}

const W = 600;
const PAD = { l: 44, r: 8, t: 8, b: 22 };

/** Dependency-free SVG chart. Has a text summary + data table fallback for accessibility. */
export function Chart({ kind, labels, series, format = String, title, height = 170 }: Props) {
  const H = height;
  const max = Math.max(...series.flatMap((s) => s.values), 0.0001) * 1.1;
  const slot = (W - PAD.l - PAD.r) / labels.length;
  const x = (i: number) => PAD.l + slot * (i + 0.5);
  const y = (v: number) => H - PAD.b - (v / max) * (H - PAD.t - PAD.b);
  const ticks = [0, max / 2, max];
  const step = Math.ceil(labels.length / 7);
  const bw = (slot * 0.7) / series.length;

  return (
    <figure className="chart">
      <figcaption className="sr-only">{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${series.map((s) => `${s.name}: latest ${format(s.values[s.values.length - 1])}`).join('; ')}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid-line" />
            <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{format(t)}</text>
          </g>
        ))}
        {labels.map((l, i) => i % step === 0 && (
          <text key={l} x={x(i)} y={H - 6} textAnchor="middle" className="axis">{l}</text>
        ))}
        {kind === 'bar' &&
          series.map((s, si) =>
            s.values.map((v, i) => (
              <rect key={`${s.name}${i}`} x={x(i) - (bw * series.length) / 2 + si * bw} y={y(v)} width={Math.max(bw - 1, 1)} height={H - PAD.b - y(v)} fill={s.color}>
                <title>{`${s.name} ${labels[i]}: ${format(v)}`}</title>
              </rect>
            )))}
        {kind === 'line' &&
          series.map((s) => (
            <g key={s.name}>
              <polyline fill="none" stroke={s.color} strokeWidth="2" points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
              {s.values.map((v, i) => (
                <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill={s.color}><title>{`${s.name} ${labels[i]}: ${format(v)}`}</title></circle>
              ))}
            </g>
          ))}
      </svg>
      {series.length > 1 && (
        <ul className="legend">
          {series.map((s) => (
            <li key={s.name}><span className="swatch" style={{ background: s.color }} aria-hidden="true" />{s.name}</li>
          ))}
        </ul>
      )}
      <details className="chart-data">
        <summary>View data</summary>
        <table className="table">
          <thead><tr><th scope="col">Date</th>{series.map((s) => <th scope="col" key={s.name} className="num">{s.name}</th>)}</tr></thead>
          <tbody>
            {labels.map((l, i) => (
              <tr key={l}><th scope="row">{l}</th>{series.map((s) => <td key={s.name} className="num">{format(s.values[i])}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
