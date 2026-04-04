import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Backtest from "./pages/Backtest";
import Config from "./pages/Config";
import Analysis from "./pages/Analysis";
import Data from "./pages/Data";
import Learn from "./pages/Learn";
import { ToastContainer } from "./components/common/Toast";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/backtest" element={<Backtest />} />
          <Route path="/config" element={<Config />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/data" element={<Data />} />
          <Route path="/learn" element={<Learn />} />
        </Route>
      </Routes>
      <ToastContainer />
    </BrowserRouter>
  );
}
