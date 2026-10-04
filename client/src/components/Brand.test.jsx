import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { BusinessBrand, PlatformLogo, businessInitials, wordmarkParts } from "./Brand";

vi.mock("../modules/platform/PlatformContext", () => ({ usePlatform: () => ({ name: "Business Management Platform" }) }));

it("shows the platform's own name, never a subscriber's branding", () => {
  const { container } = render(<PlatformLogo />);
  expect(container.querySelector(".platformLogoName")).toHaveTextContent("Business Management Platform");
  expect(screen.queryByText(/LinTech/i)).not.toBeInTheDocument();
});

it("shows a business's uploaded logo, or its initials and name when it has none", () => {
  const { rerender } = render(<BusinessBrand organization={{ name: "Mama Mboga Kiandas", logo_url: "" }} />);
  expect(screen.getByText("MM")).toBeInTheDocument();
  expect(screen.getByText("Mama Mboga Kiandas")).toBeInTheDocument();
  rerender(<BusinessBrand organization={{ name: "LinTechDigitalPoint", logo_url: "https://example.test/logo.png" }} />);
  expect(screen.getByRole("img", { name: "LinTechDigitalPoint" })).toHaveAttribute("src", "https://example.test/logo.png");
});

it("builds initials from spaced or joined business names", () => {
  expect(businessInitials("LinTechDigitalPoint")).toBe("LT");
  expect(businessInitials("linTech Digital Point")).toBe("LD");
  expect(businessInitials("Kiandas")).toBe("KI");
});

it("splits the platform name into a lead and an accent for the wordmark", () => {
  expect(wordmarkParts("DukaFlow")).toEqual({ lead: "Duka", accent: "Flow", joined: true });
  expect(wordmarkParts("Business Management Platform")).toEqual({ lead: "Business Management", accent: "Platform", joined: false });
  expect(wordmarkParts("Duka")).toEqual({ lead: "Duka", accent: "", joined: false });
});
