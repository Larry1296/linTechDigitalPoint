import {
  Headphones,
  MapPin,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import type { Product } from "../../types";
type HomeData = {
  store: { name: string; phone: string; email: string; address: string };
  categories: { id: number; name: string; slug: string }[];
  featured_products: Product[];
  services: Product[];
  cyber_services: { name: string; price: string; billing_unit: string }[];
};
export function HomePage() {
  const [data, setData] = useState<HomeData>();
  const [error, setError] = useState("");
  useEffect(() => {
    document.title = "LinTech Digital Point";
    api<HomeData>("/api/v1/store/home/")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  return (
    <main>
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
              <div className="heroActions">
                <Link className="button" to="/shop">
                  Shop now
                </Link>
                <a className="button secondary" href="#categories">
                  Browse categories
                </a>
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
          <section className="homeSection">
            <span className="eyebrow">From our shop</span>
            <h2>Featured products</h2>
            {data.featured_products.length ? (
              <div className="productGrid">
                {data.featured_products.map((p) => (
                  <article className="productCard" key={p.id}>
                    <div className="productImage">
                      {p.images[0] ? (
                        <img src={p.images[0].url} alt={p.images[0].alt} />
                      ) : (
                        p.product_name[0]
                      )}
                    </div>
                    <h3>{p.product_name}</h3>
                    <b>KSh {p.selling_price}</b>
                    <span
                      className={
                        p.available && +p.available > 0 ? "stock" : "out"
                      }
                    >
                      {p.available === null
                        ? "Available"
                        : +p.available > 0
                          ? "In stock"
                          : "Out of stock"}
                    </span>
                    <Link className="button" to={"/products/" + p.id}>
                      View product
                    </Link>
                  </article>
                ))}
              </div>
            ) : (
              <Empty>New products will be available here soon.</Empty>
            )}
          </section>
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
                    <span>KSh {service.price} · {service.billing_unit.replaceAll("_", " ").toLowerCase()}</span>
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
            <p>Convenient M-Pesa agent cash deposit and cash withdrawal services are available at LinTech Digital Point.</p>
            <small>Visit us for service. Charges and applicable limits are confirmed at the counter.</small>
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
