"use client";

import { createContext, useContext } from "react";
import type { Staff } from "@/lib/api";

export const StaffContext = createContext<Staff | null>(null);
export const useStaff = () => useContext(StaffContext);
