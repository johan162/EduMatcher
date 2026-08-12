/**
 * Zod schemas for order entry validation (§12.4).
 * Side is injected by the BUY/SELL button handler; validation is side-agnostic.
 */
import { z } from "zod";

export const orderSchema = z
  .object({
    symbol: z.string().min(1, "Symbol required"),
    side: z.enum(["BUY", "SELL"]),
    order_type: z.enum([
      "MARKET",
      "LIMIT",
      "STOP",
      "STOP_LIMIT",
      "FOK",
      "ICEBERG",
      "IOC",
      "TRAILING_STOP",
    ]),
    quantity: z.coerce.number().int().positive("Quantity must be a positive integer"),
    tif: z.enum(["DAY", "GTC", "ATO", "ATC"]).default("DAY"),
    price: z.coerce.number().positive().optional(),
    stop_price: z.coerce.number().positive().optional(),
    visible_qty: z.coerce.number().int().positive().optional(),
    trail_offset: z.coerce.number().positive().optional(),
    smp_action: z.enum(["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]).optional(),
    client_order_id: z.string().max(64).optional(),
  })
  .superRefine((data, ctx) => {
    if (["LIMIT", "FOK", "IOC", "STOP_LIMIT"].includes(data.order_type) && !data.price) {
      ctx.addIssue({
        code: "custom",
        path: ["price"],
        message: "Price required for this order type",
      });
    }
    if (["STOP", "STOP_LIMIT"].includes(data.order_type) && !data.stop_price) {
      ctx.addIssue({
        code: "custom",
        path: ["stop_price"],
        message: "Stop price required",
      });
    }
    if (data.order_type === "ICEBERG") {
      if (!data.visible_qty) {
        ctx.addIssue({
          code: "custom",
          path: ["visible_qty"],
          message: "Visible qty required",
        });
      } else if (data.visible_qty >= data.quantity) {
        ctx.addIssue({
          code: "custom",
          path: ["visible_qty"],
          message: "Visible qty must be less than total qty",
        });
      }
    }
    if (data.order_type === "TRAILING_STOP" && !data.trail_offset) {
      ctx.addIssue({
        code: "custom",
        path: ["trail_offset"],
        message: "Trail offset required",
      });
    }
  });

export type OrderFormValues = z.infer<typeof orderSchema>;

export const ocoSchema = z.object({
  oco_id: z.string().min(1),
  symbol: z.string().min(1),
  quantity: z.coerce.number().int().positive(),
  tif: z.enum(["DAY", "GTC"]),
  leg1: z.object({
    side: z.enum(["BUY", "SELL"]),
    order_type: z.enum(["LIMIT", "STOP"]),
    price: z.coerce.number().positive().optional(),
    stop_price: z.coerce.number().positive().optional(),
  }),
  leg2: z.object({
    side: z.enum(["BUY", "SELL"]),
    order_type: z.enum(["LIMIT", "STOP"]),
    price: z.coerce.number().positive().optional(),
    stop_price: z.coerce.number().positive().optional(),
  }),
});

export type OcoFormValues = z.infer<typeof ocoSchema>;

export const comboSchema = z.object({
  combo_id: z.string().min(1),
  combo_type: z.literal("AON").default("AON"),
  tif: z.enum(["DAY", "GTC"]).default("DAY"),
  smp_action: z.enum(["NONE", "CANCEL_AGGRESSOR", "CANCEL_RESTING", "CANCEL_BOTH"]).default("NONE"),
  legs: z
    .array(
      z.object({
        symbol: z.string().min(1),
        side: z.enum(["BUY", "SELL"]),
        order_type: z.enum(["LIMIT", "MARKET"]).default("LIMIT"),
        quantity: z.coerce.number().int().positive(),
        price: z.coerce.number().positive().optional(),
      }),
    )
    .min(2)
    .max(10),
});

export type ComboFormValues = z.infer<typeof comboSchema>;

export const quoteSchema = z
  .object({
    symbol: z.string().min(1),
    bid_price: z.coerce.number().positive(),
    bid_qty: z.coerce.number().int().positive(),
    ask_price: z.coerce.number().positive(),
    ask_qty: z.coerce.number().int().positive(),
    tif: z.enum(["DAY", "GTC"]).default("DAY"),
    quote_id: z.string().min(1),
  })
  .superRefine((d, ctx) => {
    if (d.bid_price >= d.ask_price) {
      ctx.addIssue({
        code: "custom",
        path: ["ask_price"],
        message: "Ask price must be strictly greater than bid price",
      });
    }
  });

export type QuoteFormValues = z.infer<typeof quoteSchema>;
