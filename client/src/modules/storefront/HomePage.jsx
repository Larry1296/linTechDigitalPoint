import { businessCurrency } from "../../core/organization/presentation";
import { ProductSearch } from "./components/ProductSearch";
import { ProductCard } from "./components/ProductCard";
import {
  ArrowUpRight,
  Headphones,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigationType } from "react-router-dom";
import { restoreListingPosition } from "./listingPosition";
import { api } from "../../core/api/client";
import { Empty, ErrorState, Loading } from "../../components/States";
import { ProductImage } from "./components/ProductImage";
import { ChevronLeft, ChevronRight, Cpu, MapPinned, Smartphone } from "lucide-react";
export function HomePage() {
  const location = useLocation();
  const navigationType = useNavigationType();
  const [data, setData] = useState();
  const [error, setError] = useState("");
  const [slide, setSlide] = useState(0);
  const [carouselPaused, setCarouselPaused] = useState(false);
  useEffect(() => {
    document.title = "LinTech Digital Point";
    api("/api/v1/store/home/")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  const featured = (data?.category_sections || []).flatMap((section) => section.products).slice(0, 6);
  useEffect(() => {
    if (featured.length < 2 || carouselPaused || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return undefined;
    const timer = window.setInterval(() => setSlide((current) => (current + 1) % featured.length), 5000);
    return () => window.clearInterval(timer);
  }, [featured.length, carouselPaused]);
  useEffect(() => { if (slide >= featured.length) setSlide(0); }, [slide, featured.length]);
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
              <span className="eyebrow"><span className="liveDot" /> {data.store.name}</span>
              <h1>Smart essentials. <em>Useful services.</em> One local place.</h1>
              <p>
                Shop the everyday technology you need and get dependable cyber
                services from a team close to you.
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
            <div className="heroCarousel" onMouseEnter={() => setCarouselPaused(true)} onMouseLeave={() => setCarouselPaused(false)} onFocus={() => setCarouselPaused(true)} onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setCarouselPaused(false); }}>
              {featured.length ? <>
                <div className="carouselMedia" aria-live="polite">
                  <ProductImage product={featured[slide]} large />
                  <span className="carouselBadge">Featured pick</span>
                </div>
                <div className="carouselInfo"><span className="eyebrow">{featured[slide].category}</span><h2>{featured[slide].display_name}</h2><p>From {businessCurrency()} {featured[slide].selling_price}</p><Link className="button" to={`/products/${featured[slide].id}`}>View product <ArrowUpRight size={16} /></Link></div>
                <div className="carouselControls"><button type="button" aria-label="Previous featured product" onClick={() => setSlide((slide - 1 + featured.length) % featured.length)}><ChevronLeft size={18} /></button><div aria-label="Featured product slides" className="carouselDots">{featured.map((product, index) => <button type="button" key={product.id} aria-label={`Show ${product.display_name}`} aria-current={index === slide} onClick={() => setSlide(index)} />)}</div><button type="button" aria-label="Next featured product" onClick={() => setSlide((slide + 1) % featured.length)}><ChevronRight size={18} /></button></div>
              </> : <div className="heroCard"><ShoppingBag size={50} /><b>Easy shopping.<br />Clear prices.<br />Reliable service.</b><span>Order online for pickup or delivery</span></div>}
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
          <section className="homeSection featuredSection" aria-labelledby="featured-title">
            <div className="sectionHeading"><div><span className="eyebrow">Popular right now</span><h2 id="featured-title">Featured products</h2></div><Link to="/shop">View all products →</Link></div>
            {featured.length ? <div className="featuredGrid">{featured.slice(0, 4).map((product) => <Link className="featuredTile" key={product.id} to={`/products/${product.id}`}><ProductImage product={product} /><span>{product.category}</span><h3>{product.display_name}</h3><b>{businessCurrency()} {product.selling_price}</b></Link>)}</div> : <Empty>Featured products will appear here soon.</Empty>}
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
          <section className="benefits" aria-label="Why choose LinTech">
            <article>
              <ShieldCheck />
              <b>Quality essentials</b>
              <span>Carefully selected products for everyday use.</span>
            </article>
            <article>
              <MapPinned />
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
                      {businessCurrency()} {service.price} ·{" "}
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
          <section className="homeSection serviceCards" aria-labelledby="mpesa-title">
            <span className="eyebrow">More ways we help</span><h2 id="mpesa-title">M-Pesa services</h2><div className="serviceCardGrid"><article><Smartphone /><div><b>Agent services at the counter</b><p>Convenient cash deposit and cash withdrawal services at LinTech Digital Point.</p></div></article><article><Cpu /><div><b>Cyber help when you need it</b><p>Printing, scanning, photocopying, typing and practical computer support.</p></div></article></div>
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
