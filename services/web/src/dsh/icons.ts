/** One icon language: Lucide outline icons, fixed sizes and stroke weight. */

import {
  ArrowLeftRight,
  Building2,
  ClipboardCheck,
  FileText,
  History,
  Hourglass,
  Landmark,
  LayoutDashboard,
  ListTree,
  MessageCircle,
  NotebookPen,
  ReceiptText,
  Scale,
  ScrollText,
  Table2,
  TrendingUp,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

export const iconSize = {
  xs: 12,
  sm: 14,
  md: 16,
  lg: 18,
  xl: 20,
  xxl: 24,
  xxxl: 32,
} as const;

export const iconStroke = 2;

/** Navigation destinations use one icon each, chosen for meaning. */
export const navIcons = {
  dashboard: LayoutDashboard,
  accounts: ListTree,
  "manual-journal": NotebookPen,
  approvals: ClipboardCheck,
  "trial-balance": Table2,
  invoices: FileText,
  customers: Users,
  "ar-aging": Hourglass,
  "bank-accounts": Landmark,
  reconciliation: ArrowLeftRight,
  bills: ScrollText,
  vendors: Building2,
  "ap-aging": Hourglass,
  employees: UserRound,
  "payroll-history": History,
  "tax-summary": ReceiptText,
  "profit-loss": TrendingUp,
  "balance-sheet": Scale,
  chat: MessageCircle,
} satisfies Record<string, LucideIcon>;

export type View = keyof typeof navIcons;
