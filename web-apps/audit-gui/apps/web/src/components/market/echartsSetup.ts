/**
 * The ECharts pieces the Market canvas draws, registered once. Static named
 * imports, so the bundler keeps only these; EChart.tsx loads this module on
 * demand, which puts it in its own chunk.
 */
import { CustomChart, ScatterChart } from "echarts/charts";
import { BrushComponent, GridComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([CustomChart, ScatterChart, GridComponent, TooltipComponent, BrushComponent, CanvasRenderer]);

export { echarts };
