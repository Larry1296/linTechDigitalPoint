import { ProductSearch } from "./components/ProductSearch";
import { ProductCard } from "./components/ProductCard";
import {
  Headphones,
  MapPin,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigationType } from "react-router-dom";
import { restoreListingPosition } from "./listingPosition";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
export function HomePage() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  useEffect(() => {
    document.title = "LinTech Digital Point";
    api("/api/v1/store/home/")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!data) return;
    // Wait until the destination and the collapsed mobile navbar are laid out.
    const frame = window.requestAnimationFrame(() => {
      if (navigationType === "POP" && restoreListingPosition(location.key))
        return;
      const section = location.hash
        ? document.getElementById(location.hash.slice(1))
        : null;
      if (location.hash && !section) return;
      const navbarHeight =
        document.querySelector(".appNavbar")?.getBoundingClientRect().height ||
        0;
      window.scrollTo({
        top: section
          ? Math.max(
              0,
              section.getBoundingClientRect().top +
                window.scrollY -
                navbarHeight -
                16,
            )
          : 0,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [data, location.hash, location.key, navigationType]);
  return (
    <main className="homePage">
      {error ? (
        <ErrorState message={error} />
      ) : !data ? (
        <Loading />
      ) : (
        <>
          <section className="hero">
            <div>
              <span className="eyebrow">{data.store.name}</span>
              <h1>Technology and everyday essentials, all in one place.</h1>
              <p>
                Shop mobile accessories, computer accessories, electrical
                essentials and useful services from LinTech.
              </p>
              <ProductSearch />
              <div className="heroActions">
                <Link className="button" to="/shop">
                  Shop now
                </Link>
                <Link className="button secondary" to="/#categories">
                  Browse categories
                </Link>
              </div>
            </div>
            <div className="heroCard">
              <ShoppingBag size={50} />
              <b>
                Easy shopping.
                <br />
                Clear prices.
                <br />
                Reliable service.
              </b>
              <span>Order online for pickup or delivery</span>
            </div>
          </section>
          <section id="categories" className="homeSection">
            <span className="eyebrow">Find what you need</span>
            <h2>Shop by category</h2>
            {data.categories.length ? (
              <div className="categoryGrid">
                {data.categories.map((x) => (
                  <Link to={"/shop?category=" + x.id} key={x.id}>
                    {x.name}
                    <span>Explore →</span>
                  </Link>
                ))}
              </div>
            ) : (
              <Empty>Product categories will appear here soon.</Empty>
            )}
          </section>
          {(data.category_sections || []).map((category) => (
            <section
              className="homeSection categoryProductSection"
              key={category.id}
              aria-labelledby={"category-" + category.id}
            >
              <div className="categorySectionHeading">
                <h2 id={"category-" + category.id}>{category.name}</h2>
                <Link to={"/shop?category=" + category.id}>
                  View category →
                </Link>
              </div>
              <div className="categoryProductGrid">
                {category.products.map((product) => (
                  <ProductCard key={product.id} product={product} />
                ))}
              </div>
            </section>
          ))}
          <section className="benefits">
            <article>
              <ShieldCheck />
              <b>Quality essentials</b>
              <span>Carefully selected products for everyday use.</span>
            </article>
            <article>
              <MapPin />
              <b>Convenient local shopping</b>
              <span>Order online and collect from LinTech.</span>
            </article>
            <article>
              <Truck />
              <b>Easy ordering</b>
              <span>Clear prices and a simple checkout.</span>
            </article>
          </section>
          <section id="services" className="homeSection">
            <span className="eyebrow">At your service</span>
            <h2>Cyber services</h2>
            {data.cyber_services.length ? (
              <div className="categoryGrid">
                {data.cyber_services.map((service) => (
                  <article key={service.name}>
                    <Headphones />
                    <b>{service.name}</b>
                    <span>
                      KSh {service.price} ·{" "}
                      {service.billing_unit.replaceAll("_", " ").toLowerCase()}
                    </span>
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted">
                Ask us about printing, photocopying, scanning, lamination,
                binding, typing, Windows setup and software installation.
              </p>
            )}
          </section>
          <section className="homeSection serviceSpotlight">
            <span className="eyebrow">Available at our counter</span>
            <h2>M-Pesa services</h2>
            <p>
              Convenient M-Pesa agent cash deposit and cash withdrawal services
              are available at LinTech Digital Point.
            </p>
            <small>
              Visit us for service. Charges and applicable limits are confirmed
              at the counter.
            </small>
          </section>
          <section id="contact" className="contactSection">
            <div>
              <span className="eyebrow">Contact & visit</span>
              <h2>{data.store.name}</h2>
            </div>
            <div>
              {data.store.phone && (
                <a href={"tel:" + data.store.phone}>{data.store.phone}</a>
              )}
              {data.store.email && (
                <a href={"mailto:" + data.store.email}>{data.store.email}</a>
              )}
              {data.store.address && <p>{data.store.address}</p>}
              {!data.store.phone &&
                !data.store.email &&
                !data.store.address && (
                  <p>Contact information will be available here soon.</p>
                )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
