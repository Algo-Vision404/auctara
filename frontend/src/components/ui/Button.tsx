"use client";

import { ButtonHTMLAttributes, forwardRef } from "react";
import clsx from "clsx";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "danger" | "secondary" | "ghost";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
  fullWidth?: boolean;
}

const variantClass: Record<Variant, string> = {
  primary: "btn-primary",
  danger: "btn-danger",
  secondary: "btn-secondary",
  ghost: "btn-ghost",
};

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "secondary", loading, fullWidth, className, children, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={clsx("btn-block", variantClass[variant], fullWidth && "w-full", className)}
        disabled={disabled || loading}
        {...rest}
      >
        {loading && <Loader2 size={16} className="animate-spin" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";
