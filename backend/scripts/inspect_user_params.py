import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from database import db
from models import UserLearnedParams, UserResidualModel, UserActivityResidual

app = create_app()

def inspect_user(user_id):
    with app.app_context():
        print(f"\n=== INSPECTING USER {user_id} ===")
        
        # 1. Learned Parameters (Tier 2)
        params = UserLearnedParams.query.filter_by(user_id=user_id).first()
        if params:
            print("\n[Tier 2] Learned Parameters:")
            print(f"  v_flat: {params.v_flat:.4f} m/s ({1000/params.v_flat/60:.2f} min/km)")
            print(f"  k_up:   {params.k_up:.4f}")
            print(f"  k_tech: {params.k_tech:.4f}")
            print(f"  a_param: {params.a_param:.4f}")
            print(f"  k_terrain_up: {params.k_terrain_up:.4f}")
            print(f"  k_terrain_down: {params.k_terrain_down:.4f}")
            
            # Check continuity at g=0
            # Uphill limit (g->0+): v = v_flat / (k_up * k_terrain_up)
            v_up_lim = params.v_flat / (params.k_up * params.k_terrain_up)
            pace_up_lim = (1000 / v_up_lim) / 60
            
            # Downhill limit (g->0-): v = v_flat * k_tech / k_terrain_down
            v_down_lim = params.v_flat * params.k_tech / params.k_terrain_down
            pace_down_lim = (1000 / v_down_lim) / 60
            
            print(f"\n[Continuity Check at 0% Grade]")
            print(f"  Uphill side (g=+0%): {pace_up_lim:.2f} min/km")
            print(f"  Downhill side (g=-0%): {pace_down_lim:.2f} min/km")
            print(f"  Gap: {abs(pace_up_lim - pace_down_lim):.2f} min/km")
        else:
            print("\n[Tier 2] No learned parameters found.")

        # 2. Personal-habits model (Tier 3)
        ml_model = UserResidualModel.query.filter_by(user_id=user_id).first()
        if ml_model:
            m = ml_model.metrics or {}
            print(f"\n[Tier 3] gate {'OPEN' if m.get('open') else 'closed'} ({m.get('reason')}), n_eval={m.get('n_eval')}")
            print(f"  MAPE Tier 2 {m.get('mape_t2')} vs Tier 3 {m.get('mape_t3')}")
            print(f"  Habits (% vs Tier 2): {ml_model.feature_importance}")
        else:
            print("\n[Tier 3] No model found.")

        # 3. Residual Data Stats
        count = UserActivityResidual.query.filter_by(user_id=user_id).count()
        print(f"\n[Data] Total Activity Residuals: {count}")

if __name__ == "__main__":
    inspect_user(2)
