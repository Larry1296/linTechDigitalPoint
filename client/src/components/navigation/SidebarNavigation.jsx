import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ChevronDown } from "lucide-react";

const inside = (pathname, links) => links.some(({ to }) => pathname === to || pathname.startsWith(`${to}/`));

// A collapsible group (e.g. one business: shop, Cyber, M-Pesa agent) opens on click and opens by itself when
// the page shown belongs to it. Plain sections keep their small heading and are always open.
function Group({ title, icon: Icon, links, onNavigate, iconSize }) {
  const { pathname } = useLocation();
  const current = inside(pathname, links);
  const [open, setOpen] = useState(current);
  useEffect(() => { if (current) setOpen(true); }, [current]);
  const id = `nav-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  return (
    <section className={`navGroup${current ? " current" : ""}`}>
      <button type="button" className="navGroupToggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>
        {Icon && <Icon size={iconSize} aria-hidden="true" />}
        <span>{title}</span>
        <ChevronDown size={16} aria-hidden="true" className="navGroupChevron" />
      </button>
      <div id={id} className="navGroupLinks" hidden={!open}>
        {links.map(({ to, label, icon: LinkIcon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={onNavigate}>
            {LinkIcon && <LinkIcon size={iconSize} aria-hidden="true" />}
            {label}
          </NavLink>
        ))}
      </div>
    </section>
  );
}

export function SidebarNavigation({ sections, onNavigate, label, iconSize }) {
  return (
    <nav aria-label={label}>
      {sections
        .filter((section) => section.links.length)
        .map((section) => section.collapsible
          ? <Group key={section.title} {...section} onNavigate={onNavigate} iconSize={iconSize} />
          : (
            <section key={section.title}>
              {section.title && <small>{section.title.toUpperCase()}</small>}
              {section.links.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} onClick={onNavigate}>
                  <Icon size={iconSize} aria-hidden="true" />
                  {label}
                </NavLink>
              ))}
            </section>
          ))}
    </nav>
  );
}
