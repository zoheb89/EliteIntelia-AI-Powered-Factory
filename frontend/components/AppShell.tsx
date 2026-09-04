'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect, useState} from 'react';
import {
  Home, UsersRound, Inbox, Search, LayoutDashboard, Database, LineChart, ShieldCheck,
  Rocket, Monitor, BookOpen, Settings, CloudCog, Bell, CircleHelp, Sun, Moon,
  MonitorCog, Menu, X, Briefcase, ChevronDown, Wifi, WifiOff, Workflow,
  Factory, Scale, Calculator, FileSignature,
} from 'lucide-react';
import {Brand} from './Brand';
import {useEngagement, ROLES, type RoleId} from '../lib/engagement-context';
import {WORKSPACES} from '../lib/workspaces';
import {getApiHealth} from '../lib/api';

// Navigation ordered as an enterprise delivery programme actually runs, and
// grouped so a newcomer can see the shape of the lifecycle at a glance.
const nav: ReadonlyArray<readonly [string, string, any] | readonly [string]> = [
  ['OVERVIEW'],
  ['Home', '/', Home],
  ['Delivery Factory', '/factory', Factory],
  ['Engagements', '/engagements', UsersRound],

  ['CAPTURE & DISCOVER'],
  ['Intake Center', '/intake', Inbox],
  ['Discovery & Assess', '/discovery', Search],

  ['DESIGN & DECIDE'],
  ['Platform Decision', '/factory/platform', Scale],
  ['Architecture', '/architecture', LayoutDashboard],
  ['Platform & Environment', '/platform', CloudCog],

  ['BUILD'],
  ['Data & Engineering', '/engineering', Database],
  ['Transformation Studio', '/studio', Workflow],
  ['AI & Analytics', '/ai-analytics', LineChart],

  ['ASSURE & RELEASE'],
  ['Validation & QA', '/validation', ShieldCheck],
  ['Deploy & Activate', '/deploy', Rocket],
  ['Monitoring', '/monitoring', Monitor],

  ['COMMERCIAL'],
  ['Effort & Automation', '/factory/estimate', Calculator],
  ['Statement of Work', '/factory/sow', FileSignature],

  ['PLATFORM'],
  ['Knowledge Center', '/knowledge', BookOpen],
  ['Settings', '/settings', Settings],
] as const;

export function AppShell({children}: {children: React.ReactNode}) {
  const path = usePathname();
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [mobile, setMobile] = useState(false);
  const [engOpen, setEngOpen] = useState(false);
  const [roleOpen, setRoleOpen] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const {engagementId, engagements, select, role, setRole} = useEngagement();

  // Backend reachability — surfaces misconfigured NEXT_PUBLIC_API_BASE_URL fast.
  useEffect(() => {
    let alive = true;
    const ping = () => getApiHealth().then(() => alive && setOnline(true)).catch(() => alive && setOnline(false));
    ping();
    const t = setInterval(ping, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const current = engagements.find(e => e.id === engagementId);
  const activeRole = ROLES.find(r => r.id === role) || ROLES[0];

  // When a persona is chosen, its workspaces are highlighted in the sidebar.
  const isFocus = (href: string) =>
    role !== 'all' && (activeRole.focus as readonly string[]).includes(href);
  const owns = (href: string) =>
    role !== 'all' && WORKSPACES[href]?.owners?.includes(role);

  return (
    <div className={theme === 'light' ? 'app light' : 'app'}>
      <aside className={mobile ? 'sidebar open' : 'sidebar'}>
        <Brand />

        <nav>
          {nav.map((entry, i) => {
            // A single-element entry is a group heading, not a destination.
            if (entry.length === 1) {
              return <div className="navGroup" key={`g-${i}`}>{entry[0]}</div>;
            }
            const [label, href, Icon] = entry as readonly [string, string, any];
            return (
              <Link
                key={href}
                href={href}
                onClick={() => setMobile(false)}
                className={`navItem${path === href ? ' active' : ''}${isFocus(href) || owns(href) ? ' focus' : ''}`}
              >
                <Icon size={19} />
                <span>{label}</span>
                {(isFocus(href) || owns(href)) && <i className="focusDot" />}
              </Link>
            );
          })}
        </nav>

        <div className="profile">
          <div className="avatar">EA</div>
          <div>
            <strong>{activeRole.label}</strong>
            <small>EliteInteliA Platform</small>
          </div>
        </div>
      </aside>

      {mobile && <div className="scrim" onClick={() => setMobile(false)} />}

      <main className="main">
        <header className="topbar">
          <button className="mobileMenu" onClick={() => setMobile(!mobile)}>{mobile ? <X /> : <Menu />}</button>

          {/* Engagement switcher — makes the selection global instead of per-page. */}
          <div className="switcher">
            <button className="switcherBtn" onClick={() => { setEngOpen(!engOpen); setRoleOpen(false); }}>
              <Briefcase size={16} />
              <span className="switcherLabel">{current ? current.title : 'No engagement'}</span>
              <ChevronDown size={15} />
            </button>
            {engOpen && (
              <div className="dropdown" onMouseLeave={() => setEngOpen(false)}>
                <div className="dropdownHead">Active engagement</div>
                {engagements.length === 0 && <div className="dropdownEmpty">No engagements yet</div>}
                {engagements.map(e => (
                  <button
                    key={e.id}
                    className={e.id === engagementId ? 'dropdownItem active' : 'dropdownItem'}
                    onClick={() => { select(e.id); setEngOpen(false); }}
                  >
                    <strong>{e.title}</strong>
                    <small>{e.customer} · {e.stage}</small>
                  </button>
                ))}
                <Link className="dropdownItem newItem" href="/intake" onClick={() => setEngOpen(false)}>
                  + New engagement
                </Link>
              </div>
            )}
          </div>

          {/* Role switcher — one platform, every persona. */}
          <div className="switcher">
            <button className="switcherBtn" onClick={() => { setRoleOpen(!roleOpen); setEngOpen(false); }}>
              <UsersRound size={16} />
              <span className="switcherLabel">{activeRole.short}</span>
              <ChevronDown size={15} />
            </button>
            {roleOpen && (
              <div className="dropdown wide" onMouseLeave={() => setRoleOpen(false)}>
                <div className="dropdownHead">View as role</div>
                {ROLES.map(r => (
                  <button
                    key={r.id}
                    className={r.id === role ? 'dropdownItem active' : 'dropdownItem'}
                    onClick={() => { setRole(r.id as RoleId); setRoleOpen(false); }}
                  >
                    <strong>{r.label}</strong>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="search">
            <Search size={18} />
            <input placeholder="Search engagements, assets..." />
          </div>

          <div className="topActions">
            <span className={online === false ? 'apiDot off' : online ? 'apiDot on' : 'apiDot'}
                  title={online === false ? 'Backend unreachable' : 'Backend connected'}>
              {online === false ? <WifiOff size={15} /> : <Wifi size={15} />}
              <em>{online === false ? 'API offline' : online ? 'API live' : '…'}</em>
            </span>
            <div className="appearance">
              <button onClick={() => setTheme('light')} className={theme === 'light' ? 'selected' : ''} title="Light"><Sun size={17} /></button>
              <button onClick={() => setTheme('dark')} className={theme === 'dark' ? 'selected' : ''} title="Dark"><Moon size={17} /></button>
            </div>
            <button className="iconButton"><Bell /></button>
            <button className="iconButton"><CircleHelp /></button>
            <div className="topAvatar">EA</div>
          </div>
        </header>

        <div className="content">{children}</div>
      </main>
    </div>
  );
}
