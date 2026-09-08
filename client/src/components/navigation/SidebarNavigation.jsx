import { NavLink } from "react-router-dom";

export function SidebarNavigation({ sections, onNavigate, label, iconSize }) {
  return (
    <nav aria-label={label}>
      {sections
        .filter((section) => section.links.length)
        .map(({ title, links }) => (
          <section key={title}>
            <small>{title.toUpperCase()}</small>
            {links.map(({ to, label, icon: Icon, end }) => (
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
