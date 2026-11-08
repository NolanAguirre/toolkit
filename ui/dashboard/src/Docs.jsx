import { useState } from 'react'
import { Card, CardHeader, CardSection } from 'component-library'
import './docs.css'

let DevScope = ({ children }) => children
if (import.meta.env.DEV) {
  const dev = await import('./devInspector.jsx')
  DevScope = dev.DevScope
}

const steps = [
  {
    title: 'Package locally',
    actor: 'Your machine',
    summary: 'Code + release identity + production environment',
    command: 'remote deploy <repo> <release-directory>',
    detail: 'The release directory contains one folder per service, each with an executable run file. The command packages every service before contacting a host. It does not build the application.',
    paths: '<release-directory>/<service>/ → <service>.tar.gz + <service>.release + <service>.env',
    note: 'For one service: remote deploy <repo> <service> <service-directory>. That directory contains run directly. Artifacts may contain regular files and directories; run must keep the application in the foreground.',
  },
  {
    title: 'Send over SSH',
    actor: 'Deploy user → root runner',
    summary: 'A bundle travels to each selected host',
    command: 'SSH stdin → s6-sudod → host deploy step',
    detail: 'The toolkit sends one bundle per target through SSH. The existing SSH user is allowed to request specific host operations through a local root runner. Hosts deploy in parallel; services on each host deploy in order.',
    paths: '/run/toolkit-remote/sudod.sock → /usr/local/lib/toolkit-remote/',
    note: 'With no --to option, remote deploy uses every configured target. Use --to to select targets. SSH requires a known host key and noninteractive authentication.',
  },
  {
    title: 'Prepare a release',
    actor: 'Root + service owner',
    summary: 'Extract code, snapshot env, prepare writable data',
    command: '/var/service-dir/<repo>-<service>/bin/deploy',
    detail: 'The host checks the archive hash and extracts the code as the service owner. Root writes release metadata and a private environment snapshot. WRITE_DIR is prepared for the runtime user. An optional deploy-prepare hook runs as the owner before activation.',
    paths: 'server/<release>/ + releases/<release> + releases/<release>.env/',
    note: 'current only changes after extraction, preparation, environment, and metadata succeed. The code owner and runtime account are separate.',
  },
  {
    title: 'Switch & restart',
    actor: 'Service owner → s6 → runtime user',
    summary: 'Point current at new code, then restart the process',
    command: 'current → <new-release>   ·   s6-svc -t <service-directory>',
    detail: 'The owner switches server/current to the new release. Old releases and their environment snapshots are pruned. s6 receives a termination request and starts the service again; the runner drops to the runtime user before loading the release environment and executing run.',
    paths: '/var/service/<repo>-<service> → /var/service-dir/<repo>-<service>',
    note: 'The default keeps four releases, plus an older release if its process is still running. A switched link is not proof that the new application is healthy. Check the host for the running process and release identity.',
  },
]

const permissions = [
  ['Service root, env/, etc/, bin/, log/, releases/', 'root', '755', 'Root can write; other users can read and traverse.'],
  ['server/ and release directories', 'acme-apiowner', '755', 'The owner installs code. The runtime account can read and execute it.'],
  ['data/ (default WRITE_DIR)', 'acme-api', '700', 'Only the runtime account can access application data, apart from root.'],
  ['log/main/', 'acme-apilog', '755', 'The logger writes here. Individual log file modes are managed by s6-log.'],
  ['run, log/run, bin/deploy', 'root', '755', 'Service accounts can execute these scripts but cannot edit them.'],
  ['releases/<release>.env/', 'root : runtime group', '750', 'Root writes; the runtime group can read and traverse; others have no access.'],
  ['Environment files inside that snapshot', 'root : runtime group', '640', 'Root can write; the runtime group can read; others have no access.'],
  ['release, running-release, releases/<release>, env/PORT', 'root', '644', 'Root can write; other users can read the metadata and setup port.'],
]

export default function Docs() {
  const [step, setStep] = useState(0)
  const selectedStep = steps[step]

  return <div className="docs">
    <DevScope id="az4fkyn"><nav className="docs-index" aria-label="Documentation">
      <span className="eyebrow">DOCS / DEPLOYMENTS</span>
      <a href="#docs-overview" aria-current="page">How deployments work</a>
      <a href="#docs-flow">The process</a>
      <a href="#docs-layout">Directory map</a>
      <a href="#docs-access">Users & permissions</a>
      <a href="#docs-runtime">Environment & runtime</a>
      <a href="#docs-setup">Setup & details</a>
    </nav></DevScope>

    <article aria-labelledby="docs-title">
      <div id="docs-overview">
        <span className="eyebrow">FROM LOCAL CODE TO A RUNNING SERVICE</span>
        <h1 id="docs-title">What a deployment looks like</h1>
        <p className="docs-lead">Package on your machine. Send to the host. Install a new release. Point <code>current</code> at it and let s6 restart the app.</p>
        <div className="docs-key"><span>Guide to the toolkit scripts</span><span>Example: repo <code>acme</code>, service <code>api</code></span><span className="docs-live-key">Green marks the selected release</span></div>
        <p className="docs-note">This is an example layout, not live host status. In the workspace, open <strong>Deployments → Check host via SSH</strong> to see what is actually running.</p>
      </div>

      <section id="docs-flow" aria-labelledby="docs-flow-title">
        <h2 id="docs-flow-title">One deployment, four steps</h2>
        <p>Select a step to see who does the work and what changes.</p>
        <ol className="docs-flow">
          {steps.map((item, index) => <li key={item.title}>
            <DevScope id="ur5yl42" state={{ step: index }}><button type="button" aria-pressed={step === index} aria-controls="docs-step-detail" onClick={() => setStep(index)}>
              <span className="docs-step-number">0{index + 1} / {item.actor}</span>
              <strong>{item.title}</strong>
              <small>{item.summary}</small>
            </button></DevScope>
          </li>)}
        </ol>
        <div id="docs-step-detail" className="docs-step-detail" aria-live="polite" aria-atomic="true">
          <DevScope id="h9jt2v3" state={{ step }}><Card><CardSection>
            <h3>{step + 1}. {selectedStep.title}</h3>
            <p>{selectedStep.detail}</p>
            <p className="docs-command"><code>{selectedStep.command}</code></p>
            <p><code>{selectedStep.paths}</code></p>
            <p className="hint">{selectedStep.note}</p>
          </CardSection></Card></DevScope>
        </div>
      </section>

      <section id="docs-layout" aria-labelledby="docs-layout-title">
        <h2 id="docs-layout-title">Where everything lives</h2>
        <p>Each deployed service gets its own directory and accounts. <code>&lt;release&gt;</code> below means one generated release ID.</p>
        <div className="docs-boundaries">
          <DevScope id="3edgu30"><Card>
            <CardHeader>Your machine · repository</CardHeader>
            <CardSection>
              <ul className="docs-tree">
                <li><code>acme/</code><ul>
                  <li><code>services/api/</code><ul>
                    <li><code>env-dir/production/</code><small>Production values, one file per key</small></li>
                    <li><code>env-dir/default/</code><small>Fills keys missing from production</small></li>
                    <li><code>remote-services</code><small>Optional deployment names and ports</small></li>
                  </ul></li>
                  <li><code>.release/&lt;timestamp&gt;/api/</code><small>Example package location; an explicit release directory also works</small><ul>
                    <li><code>run</code><small>Executable application entry point</small></li>
                    <li><code>…built application files</code></li>
                  </ul></li>
                </ul></li>
              </ul>
              <p className="hint">Code, metadata, and environment files travel together in the SSH bundle. The environment is separate from the code archive.</p>
            </CardSection>
          </Card></DevScope>
          <div className="docs-transfer" aria-label="Sent over SSH">→</div>
          <DevScope id="920xrne"><Card>
            <CardHeader>Remote host · acme-api</CardHeader>
            <CardSection>
              <ul className="docs-tree">
                <li><code>/var/service/acme-api</code><small>s6 watches this link → /var/service-dir/acme-api</small></li>
                <li><code>/var/service-dir/acme-api/</code><ul>
                  <li><code>run · bin/deploy · bin/toolkit-host.sh</code><small>Root-owned runner and deployment tools</small></li>
                  <li><code>env/PORT · etc/</code><small>Setup-time port and configuration directory</small></li>
                  <li><code>server/</code><small>Owned by acme-apiowner</small><ul>
                    <li><code>&lt;previous-release&gt;/</code><small>Retained code</small></li>
                    <li><code>&lt;new-release&gt;/run</code><small>New artifact and its entry point</small></li>
                    <li className="docs-current"><code>current → &lt;new-release&gt;</code><small>The next process starts from this release</small></li>
                  </ul></li>
                  <li><code>data/</code><small>Runtime-owned writable data; survives code releases</small></li>
                  <li><code>log/run · log/main/</code><small>Logger runner and logger-owned output directory</small></li>
                  <li><code>releases/&lt;release&gt;</code><small>Release identity and archive hash</small></li>
                  <li><code>releases/&lt;release&gt;.env/</code><small>Private environment snapshot for that release</small></li>
                  <li><code>release · running-release</code><small>Selected metadata; process identity recorded at startup</small></li>
                </ul></li>
              </ul>
            </CardSection>
          </Card></DevScope>
        </div>
        <p className="docs-note">Deploying changes the code and its environment snapshot. Application writes belong in <code>WRITE_DIR</code>, which defaults to <code>/var/service-dir/acme-api/data</code>.</p>
      </section>

      <section id="docs-access" aria-labelledby="docs-access-title">
        <h2 id="docs-access-title">Who can change what</h2>
        <p>The SSH user requests deployment. Root manages the service layout. Three separate accounts own the service’s work.</p>
        <div className="docs-roles">
          <DevScope id="v2aqvim"><Card><CardHeader><h3>acme-apiowner</h3></CardHeader><CardSection><strong>Installs code</strong><p>Owns <code>server/</code>, extracts releases, runs the optional preparation hook, and switches <code>current</code>.</p><p className="hint">Home: server/ · no login shell</p></CardSection></Card></DevScope>
          <DevScope id="zuctlfl"><Card><CardHeader><h3>acme-api</h3></CardHeader><CardSection><strong>Runs the app</strong><p>Reads the release and its environment. Writes application data in <code>data/</code> by default.</p><p className="hint">Home: data/ · no login shell</p></CardSection></Card></DevScope>
          <DevScope id="tww6buz"><Card><CardHeader><h3>acme-apilog</h3></CardHeader><CardSection><strong>Writes logs</strong><p>Runs <code>s6-log</code> and owns <code>log/main/</code>. Default rotation uses 1 MiB files with 100 retained.</p><p className="hint">Home: log/main/ · no login shell</p></CardSection></Card></DevScope>
        </div>
        <div className="table-scroll docs-permissions" tabIndex={0} role="region" aria-label="Service ownership and permissions">
          <table>
            <caption>Modes set by the toolkit. Digits describe owner / group / others: 7 = read, write, execute; 6 = read, write; 5 = read, execute; 4 = read; 0 = none. On directories, execute means traversal.</caption>
            <thead><tr><th scope="col">Path inside the service</th><th scope="col">Owner</th><th scope="col">Mode</th><th scope="col">Meaning</th></tr></thead>
            <tbody>{permissions.map(([path, owner, mode, meaning]) => <DevScope id="koczyhq" key={path} state={{ path }}><tr><td><code>{path}</code></td><td><code>{owner}</code></td><td><code>{mode}</code></td><td>{meaning}</td></tr></DevScope>)}</tbody>
          </table>
        </div>
        <p className="docs-note">Packaged code removes group/other write access and special permission bits, and preserves executable entry points. The runtime account does not own the code. Root remains able to access the service’s files.</p>
      </section>

      <section id="docs-runtime" aria-labelledby="docs-runtime-title">
        <h2 id="docs-runtime-title">Environment in, process out</h2>
        <DevScope id="v6v78k1"><Card><CardSection>
          <div className="docs-runtime" aria-label="Production environment takes priority over defaults, then becomes a release snapshot">
            <code>production + missing defaults</code><span aria-hidden="true">→</span><code>releases/&lt;release&gt;.env/</code><span aria-hidden="true">→</span><code>runtime process</code>
          </div>
          <p>Production values win. Even an empty production value blocks its default. Personal <code>env-dir/$USER</code> files are not read; <code>ENV_USER</code> is forced to <code>production</code>. The registered port replaces <code>PORT</code> in the snapshot.</p>
          <p>The runner reads the setup environment, drops to <code>acme-api</code>, reads the release snapshot, then executes that release’s <code>run</code>. Environment files cross the SSH connection and are stored on the host with the private modes above.</p>
          <p className="hint">An explicit WRITE_DIR must be an absolute path without dot segments or symlink parents. If it already exists, it must already belong to the runtime user.</p>
        </CardSection></Card></DevScope>
        <p className="docs-note"><strong>Selected and running can differ.</strong> <code>server/current</code> selects code for the next start. <code>running-release</code> records the process identity when it starts. Use host status to compare them; deployment success does not include an application health check.</p>
      </section>

      <section id="docs-setup" aria-labelledby="docs-setup-title">
        <h2 id="docs-setup-title">Setup & finer details</h2>
        <DevScope id="s2oqu82"><details>
          <summary>What must exist before the first deployment?</summary>
          <ol>
            <li><p>On an Ubuntu host, <code>sudo remote this install-dependencies</code> installs dependencies. It does not install the deployment runner.</p></li>
            <li><p>On the host, <code>sudo remote this setup-deploy &lt;deploy-user&gt;</code> installs the root runner and allows an existing SSH user to use it. It also adds that user to the shared port group.</p></li>
            <li><p>From your machine, <code>remote setup all &lt;repo&gt;</code> creates service users, directories, runners, and supervision. It does not copy application code. s6 can attempt to start the service before the first valid release exists.</p></li>
          </ol>
          <p>The root runner uses <code>/run/toolkit-remote/sudod.sock</code>, UID rules under <code>/etc/toolkit-remote/rules/uid/</code>, and the host lock <code>/var/run/toolkit-remote.lock</code>. Only allowed UIDs can request the supported host operations.</p>
        </details></DevScope>
        <DevScope id="qze6p86"><details>
          <summary>What happens if a deployment fails?</summary>
          <p>Local packaging finishes for every service before any SSH transfer. On the host, preparation must finish before <code>current</code> changes. A failed extraction can leave an unused release directory.</p>
          <p>Deployment is not a transaction across services or hosts. An earlier service may already be updated when another fails. Restarting also does not prove the app is healthy. Check host status before retrying; retained releases do not provide automatic rollback.</p>
        </details></DevScope>
        <DevScope id="d9mx7eg"><details>
          <summary>How do I know which code was deployed?</summary>
          <p>Release metadata includes the archive SHA-256. By default, the Git commit is observed in the registered checkout at deploy time, and a dirty checkout is allowed. This does not prove which commit produced an existing artifact.</p>
          <p>An optional <code>.toolkit-commit</code> file in the artifact supplies the packaged commit identity. The dashboard distinguishes packaged commit metadata from checkout-at-deploy metadata.</p>
        </details></DevScope>
        <DevScope id="agcaq6c"><details>
          <summary>Is the deployment/ template the same process?</summary>
          <p>The process above is <code>remote deploy</code>, used by the dashboard. It ships code and restarts s6.</p>
          <p>The separate application-owned <code>deployment/deploy</code> template calls <code>install → setup → stop → migrate → activate → start → status</code>. Those application scripts are not supplied, and <code>remote deploy</code> does not call this sequence or run database migrations.</p>
          <p>The template’s <code>make deployment.push</code> calls build, package, and remote deploy. It expects application-specific scripts and a configured repository name; it is not a ready-made build pipeline.</p>
        </details></DevScope>
        <DevScope id="8ua3anu"><details>
          <summary>Source files behind this guide</summary>
          <dl className="docs-source-list">
            <dt><code>src/remote.bin/remote-deploy</code></dt><dd>Local packaging, environment precedence, release identity, and transfer.</dd>
            <dt><code>src/remote.bin/validate</code></dt><dd>Targets, deployment service names, ports, and input checks.</dd>
            <dt><code>src/lib/remote-host.sh</code></dt><dd>Service accounts, filesystem ownership, runtime runner, release installation, and retention.</dd>
            <dt><code>src/remote.bin/.host/</code></dt><dd>Host setup, service scripts, supervision, and deployment dispatch.</dd>
            <dt><code>src/remote.bin/this/setup-deploy</code></dt><dd>Root runner, UID access rules, and deploy-user setup.</dd>
            <dt><code>src/bootstrap.bin/template/deployment/</code></dt><dd>Separate application-owned deployment template.</dd>
          </dl>
        </details></DevScope>
      </section>
    </article>
  </div>
}
