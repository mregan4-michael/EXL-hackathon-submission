// Shape of the generated app.g.ts (written by factory.generate.emit).
export type Widget = "text" | "date" | "select" | "checkbox" | "label" | "button";

export interface ControlDef {
  name: string;
  type: string;
  widget: string;
  source: string;
  rules: Record<string, string>;
  computed: string[];
  options?: string[];
  label?: string;
}

export interface ScreenDef {
  screen: string;
  controls: ControlDef[];
}

export interface ActionDef {
  screen: string;
  control: string;
  table: string;
  operation: string;
  contextFields: string[];
  row: string | null;
}

export interface ContainerDef {
  table: string;
  entitySet: string;
  fields: string[];
}

export interface AppDefinition {
  appId: string;
  screens: ScreenDef[];
  actions: ActionDef[];
  containers: ContainerDef[];
}

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
export type Row = Record<string, Json>;

export interface DemoUser {
  email: string;
  role: string;
  businessUnit: string;
}

export interface Evaluation {
  values: Record<string, Json>;
  errors: Record<string, string>;
}
