import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, "../.env") });

export const config = {
  port: process.env.PORT || 3000,
  brainUrl: process.env.BRAIN_URL || "http://localhost:8000",
  authDir: process.env.AUTH_DIR || path.resolve(__dirname, "../auth_state"),
};

