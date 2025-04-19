import streamlit as st
import pulp
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from copy import deepcopy

# --- Constants and Configuration ---
# Default values, these can be overridden by user input below

# Ingredients
INGREDIENTS = ['Coffee Beans', 'Milk Foam', 'Steamed Milk', 'Chocolate Powder']
DRINKS = ['Cappuccino', 'Latte', 'Mocha']
DAYS = list(range(7))
DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

# Default Costs per kg
DEFAULT_STANDARD_COSTS = {
    'Coffee Beans': 14.0, 'Milk Foam': 8.0, 'Steamed Milk': 6.0, 'Chocolate Powder': 5.0
}
# Default Thursday discount rate (e.g., 0.15 for 15%)
DEFAULT_THURSDAY_DISCOUNT_RATE = 0.15

# Default Inventory holding costs per kg per day
DEFAULT_HOLDING_COSTS = {
    'Coffee Beans': 2.6, 'Milk Foam': 0.6, 'Steamed Milk': 1.0, 'Chocolate Powder': 0.3
}

# Days when ordering is NOT allowed (0-indexed: Tue, Fri)
NO_ORDER_DAYS = [1, 4]

# Ingredient quantities per drink (kg) - ASSUMPTIONS
KG_PER_DRINK = {
    'Coffee Beans':     {'Cappuccino': 0.040, 'Latte': 0.025, 'Mocha': 0.030},
    'Milk Foam':        {'Cappuccino': 0.010, 'Latte': 0.005, 'Mocha': 0.0},
    'Steamed Milk':     {'Cappuccino': 0.010, 'Latte': 0.020, 'Mocha': 0.020},
    'Chocolate Powder': {'Cappuccino': 0.0,   'Latte': 0.0,   'Mocha': 0.015}
}

# Predicted weekly sales (used if 'Use Predicted Demand' is checked)
PREDICTED_SALES = {
    'Cappuccino': np.array([51, 48, 55, 113, 136, 112, 69]),
    'Latte':      np.array([80, 43, 56, 94, 120, 140, 64]),
    'Mocha':      np.array([55, 45, 58, 131, 165, 132, 83])
}

# --- Helper Function: Calculate Demand ---
# (No changes needed in this function)
def calculate_demand_from_sales(daily_sales):
    """Calculates ingredient demand based on drink sales."""
    demand_kg = {ing: np.zeros(len(DAYS)) for ing in INGREDIENTS}
    for ing in INGREDIENTS:
        for drink in DRINKS:
            # Check if ingredient is used in the drink and recipe exists
            if drink in KG_PER_DRINK.get(ing, {}):
                 demand_kg[ing] += daily_sales[drink] * KG_PER_DRINK[ing][drink]

    # Format into the dictionary structure needed by the solver
    demand_dict = {
        ing: {day: demand_kg[ing][day] for day in DAYS} for ing in INGREDIENTS
    }
    return demand_dict

# --- Core LP Solver Function ---
# Modified to accept cost parameters
def solve_ordering_plan(demand, standard_costs, thursday_discount_rate, holding_costs):
    """Solves the LP model for material ordering using provided cost parameters."""

    # Calculate Thursday costs based on the discount rate
    thursday_costs = {k: v * (1 - thursday_discount_rate) for k, v in standard_costs.items()}

    # Create effective cost dictionary: cost[ingredient][day]
    effective_cost = {}
    for ing in INGREDIENTS:
        effective_cost[ing] = {}
        for day in DAYS:
            effective_cost[ing][day] = thursday_costs[ing] if day == 3 else standard_costs[ing]

    # Create the minimization problem
    prob = pulp.LpProblem("Material_Ordering_Plan_UI_Dynamic", pulp.LpMinimize) # Renamed for clarity

    # Define Decision Variables
    order_vars = pulp.LpVariable.dicts("Order",
                                       ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                       lowBound=0, cat='Continuous')
    inventory_vars = pulp.LpVariable.dicts("Inventory",
                                           ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                           lowBound=0, cat='Continuous')

    # Define Objective Function - using passed holding_costs and calculated effective_cost
    prob += pulp.lpSum(effective_cost[ing][day] * order_vars[ing, day] for ing in INGREDIENTS for day in DAYS) + \
            pulp.lpSum(holding_costs[ing] * inventory_vars[ing, day] for ing in INGREDIENTS for day in DAYS), \
            "Total Cost"

    # Define Constraints
    # Inventory Balance
    for ing in INGREDIENTS:
        for day in DAYS:
            if day == 0:
                prob += inventory_vars[ing, day] == order_vars[ing, day] - demand[ing][day], \
                        f"Inv_Balance_{ing}_Day_{day}"
            else:
                prob += inventory_vars[ing, day] == inventory_vars[ing, day-1] + order_vars[ing, day] - demand[ing][day], \
                        f"Inv_Balance_{ing}_Day_{day}"
    # Ordering Restriction
    for ing in INGREDIENTS:
        for day in NO_ORDER_DAYS:
            prob += order_vars[ing, day] == 0, f"No_Order_{ing}_Day_{day}"

    # Solve the Problem
    # Set a short timeout for the solver (e.g., 10 seconds)
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=10) 
    prob.solve(solver)

    # --- Extract Results ---
    results = {"status": pulp.LpStatus[prob.status]}
    if prob.status == pulp.LpStatusOptimal:
        results["total_cost"] = pulp.value(prob.objective)

        # Extract order quantities
        order_plan = pd.DataFrame(index=INGREDIENTS, columns=DAY_NAMES, dtype=float)
        for ing in INGREDIENTS:
            for day in DAYS:
                order_val = order_vars[ing, day].varValue
                order_plan.loc[ing, DAY_NAMES[day]] = order_val if order_val is not None and order_val > 1e-6 else 0.0

        # Extract inventory levels
        inventory_levels = pd.DataFrame(index=INGREDIENTS, columns=DAY_NAMES, dtype=float)
        for ing in INGREDIENTS:
            for day in DAYS:
                inv_val = inventory_vars[ing, day].varValue
                inventory_levels.loc[ing, DAY_NAMES[day]] = inv_val if inv_val is not None and inv_val > 1e-6 else 0.0

        results["order_plan_df"] = order_plan
        results["inventory_levels_df"] = inventory_levels
        
    elif prob.status == pulp.LpStatusNotSolved:
        results["status"] = "TimeLimitReached" # Provide a more specific status


    return results

def enhanced_solve_ordering_plan(demand, standard_costs, thursday_discount_rate, holding_costs, 
                          expiry_days=None, min_order_quantities=None, stockout_costs=None, 
                          ordering_days=None, max_solver_time=20):
    """
    Enhanced LP solver that includes additional features:
    - Ingredient expiry constraints
    - Minimum order quantities
    - Stockout costs
    - Custom ordering days
    """
    # Calculate Thursday costs based on the discount rate
    thursday_costs = {k: v * (1 - thursday_discount_rate) for k, v in standard_costs.items()}

    # Create effective cost dictionary: cost[ingredient][day]
    effective_cost = {}
    for ing in INGREDIENTS:
        effective_cost[ing] = {}
        for day in DAYS:
            effective_cost[ing][day] = thursday_costs[ing] if day == 3 else standard_costs[ing]

    # Create the minimization problem
    prob = pulp.LpProblem("Enhanced_Material_Ordering_Plan", pulp.LpMinimize)

    # Define Decision Variables
    order_vars = pulp.LpVariable.dicts("Order",
                                     ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                     lowBound=0, cat='Continuous')
    
    inventory_vars = pulp.LpVariable.dicts("Inventory",
                                         ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                         lowBound=0, cat='Continuous')
    
    # Define stockout variables if needed
    stockout_vars = None
    if stockout_costs:
        stockout_vars = pulp.LpVariable.dicts("Stockout",
                                           ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                           lowBound=0, cat='Continuous')
    
    # Define binary variables for minimum order quantities if needed
    order_decision_vars = None
    if min_order_quantities:
        order_decision_vars = pulp.LpVariable.dicts("OrderDecision",
                                                 ((ing, day) for ing in INGREDIENTS for day in DAYS),
                                                 cat='Binary')

    # Define Objective Function
    obj_function = pulp.lpSum(effective_cost[ing][day] * order_vars[ing, day] 
                            for ing in INGREDIENTS for day in DAYS) + \
                 pulp.lpSum(holding_costs[ing] * inventory_vars[ing, day] 
                            for ing in INGREDIENTS for day in DAYS)
    
    # Add stockout costs to objective function if applicable
    if stockout_costs:
        obj_function += pulp.lpSum(stockout_costs[ing] * stockout_vars[ing, day]
                                for ing in INGREDIENTS for day in DAYS)
    
    prob += obj_function, "Total Cost"

    # Define Constraints
    # Inventory Balance
    for ing in INGREDIENTS:
        for day in DAYS:
            if stockout_costs:  # If we're handling stockouts
                if day == 0:
                    prob += inventory_vars[ing, day] - stockout_vars[ing, day] == \
                            order_vars[ing, day] - demand[ing][day], \
                            f"Inv_Balance_{ing}_Day_{day}"
                else:
                    prob += inventory_vars[ing, day] - stockout_vars[ing, day] == \
                            inventory_vars[ing, day-1] + order_vars[ing, day] - demand[ing][day], \
                            f"Inv_Balance_{ing}_Day_{day}"
            else:  # Standard inventory balance
                if day == 0:
                    prob += inventory_vars[ing, day] == order_vars[ing, day] - demand[ing][day], \
                            f"Inv_Balance_{ing}_Day_{day}"
                else:
                    prob += inventory_vars[ing, day] == inventory_vars[ing, day-1] + \
                            order_vars[ing, day] - demand[ing][day], \
                            f"Inv_Balance_{ing}_Day_{day}"
    
    # Ordering Restriction - use custom ordering days if provided, else use default NO_ORDER_DAYS
    no_order_days_to_use = NO_ORDER_DAYS
    if ordering_days is not None:
        no_order_days_to_use = [day for day in DAYS if day not in ordering_days]
    
    for ing in INGREDIENTS:
        for day in no_order_days_to_use:
            prob += order_vars[ing, day] == 0, f"No_Order_{ing}_Day_{day}"
    
    # Minimum Order Quantity constraints
    if min_order_quantities and order_decision_vars:
        for ing in INGREDIENTS:
            min_qty = min_order_quantities.get(ing, 0)
            if min_qty > 0:
                for day in DAYS:
                    if day not in no_order_days_to_use:
                        # If ordered, must be at least min_qty
                        prob += order_vars[ing, day] <= 1000 * order_decision_vars[ing, day], \
                                f"Order_Decision_Upper_{ing}_{day}"
                        prob += order_vars[ing, day] >= min_qty * order_decision_vars[ing, day], \
                                f"Min_Order_{ing}_{day}"
    
    # Expiry constraints - ensure inventory age doesn't exceed expiry days
    if expiry_days:
        # This is a simplified approach - for each ingredient with an expiry constraint
        # we ensure that inventory ordered on a specific day is used within its expiry period
        for ing in INGREDIENTS:
            max_days = expiry_days.get(ing)
            if max_days and max_days > 0 and max_days < len(DAYS):
                for start_day in range(len(DAYS) - max_days + 1):
                    end_day = start_day + max_days - 1
                    # Sum of orders from start to end must equal sum of demand in that period
                    if end_day < len(DAYS):
                        total_orders = pulp.lpSum(order_vars[ing, day] for day in range(start_day, end_day + 1))
                        total_demand = pulp.lpSum(demand[ing][day] for day in range(start_day, end_day + 1))
                        # Ensure we don't order more than can be consumed within expiry period
                        prob += total_orders <= total_demand + \
                                (0 if start_day == 0 else inventory_vars[ing, start_day-1]), \
                                f"Expiry_{ing}_StartDay_{start_day}_EndDay_{end_day}"

    # Solve the Problem
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=max_solver_time)
    prob.solve(solver)

    # --- Extract Results ---
    results = {"status": pulp.LpStatus[prob.status]}
    
    if prob.status == pulp.LpStatusOptimal:
        results["total_cost"] = pulp.value(prob.objective)

        # Extract order quantities
        order_plan = pd.DataFrame(index=INGREDIENTS, columns=DAY_NAMES, dtype=float)
        for ing in INGREDIENTS:
            for day in DAYS:
                order_val = order_vars[ing, day].varValue
                order_plan.loc[ing, DAY_NAMES[day]] = order_val if order_val is not None and order_val > 1e-6 else 0.0

        # Extract inventory levels
        inventory_levels = pd.DataFrame(index=INGREDIENTS, columns=DAY_NAMES, dtype=float)
        for ing in INGREDIENTS:
            for day in DAYS:
                inv_val = inventory_vars[ing, day].varValue
                inventory_levels.loc[ing, DAY_NAMES[day]] = inv_val if inv_val is not None and inv_val > 1e-6 else 0.0

        results["order_plan_df"] = order_plan
        results["inventory_levels_df"] = inventory_levels
        
        # Extract stockout information if applicable
        if stockout_vars:
            stockout_levels = pd.DataFrame(index=INGREDIENTS, columns=DAY_NAMES, dtype=float)
            for ing in INGREDIENTS:
                for day in DAYS:
                    stockout_val = stockout_vars[ing, day].varValue
                    stockout_levels.loc[ing, DAY_NAMES[day]] = stockout_val if stockout_val is not None and stockout_val > 1e-6 else 0.0
            results["stockout_levels_df"] = stockout_levels
        
    elif prob.status == pulp.LpStatusNotSolved:
        results["status"] = "TimeLimitReached"  # Provide a more specific status

    return results

# --- Helper Functions for Extensions ---
def apply_seasonal_factors(sales_data, seasonal_factors):
    """Apply seasonal adjustment factors to sales data."""
    adjusted_sales = deepcopy(sales_data)
    
    for drink in adjusted_sales:
        for day_idx, day_name in enumerate(DAY_NAMES):
            factor = seasonal_factors.get(day_name, 1.0)
            adjusted_sales[drink][day_idx] = int(adjusted_sales[drink][day_idx] * factor)
            
    return adjusted_sales

def create_new_drink(name, recipe):
    """Add a new drink to the system with its recipe."""
    # Add drink name to the list
    if name in DRINKS:
        return False, f"Drink '{name}' already exists."
    
    # Add recipe for each ingredient
    for ing in INGREDIENTS:
        if ing not in KG_PER_DRINK:
            KG_PER_DRINK[ing] = {}
        KG_PER_DRINK[ing][name] = recipe[ing]
    
    # Add the drink to the global list
    DRINKS.append(name)
    
    return True, f"Drink '{name}' added successfully."

def run_sensitivity_analysis(base_demand, base_costs, parameter_name, values, current_value, 
                           holding_costs, thursday_discount=None):
    """Run a sensitivity analysis by varying one parameter and solving the model for each value."""
    results = []
    
    for val in values:
        if parameter_name == 'thursday_discount':
            # Vary Thursday discount rate
            result = solve_ordering_plan(
                base_demand, base_costs, val, holding_costs
            )
        elif parameter_name == 'holding_cost_factor':
            # Vary holding costs by a factor
            modified_holding_costs = {ing: cost * val for ing, cost in holding_costs.items()}
            result = solve_ordering_plan(
                base_demand, base_costs, thursday_discount, modified_holding_costs
            )
        elif parameter_name == 'demand_factor':
            # Vary demand by a factor
            modified_demand = {}
            for ing in INGREDIENTS:
                modified_demand[ing] = {day: base_demand[ing][day] * val for day in DAYS}
            result = solve_ordering_plan(
                modified_demand, base_costs, thursday_discount, holding_costs
            )
            
        if result["status"] == 'Optimal':
            results.append((val, result["total_cost"]))
        else:
            results.append((val, None))
            
    return results

# --- Streamlit User Interface ---

st.set_page_config(layout="wide") # Use wide layout for better table display
st.title("☕ Coffee Shop Material Ordering Planner")

# --- Input Sections in Columns ---
input_col1, input_col2 = st.columns([3, 2]) # Allocate more space for demand inputs

with input_col1:
    st.header("1. Demand Input")
    
    # Check if we need to switch to manual input mode (after adding new drink)
    if "force_manual_input" in st.session_state and st.session_state["force_manual_input"]:
        use_predicted_initial = False
        # Clear the flag
        del st.session_state["force_manual_input"]
    else:
        use_predicted_initial = True
    
    # Option to use predicted demand
    use_predicted = st.checkbox("Use Predicted Demand (ignores manual inputs below)", 
                               value=use_predicted_initial, 
                               key="use_predicted_demand")

    st.subheader("Daily Drink Sales Forecast (Units)")
    # Initialize dictionary to store user inputs
    manual_sales = {drink: np.zeros(len(DAYS), dtype=int) for drink in DRINKS}

    # Use st.data_editor for a more compact input table
    # Prepare data for the editor
    demand_data = {}
    for i, day_name in enumerate(DAY_NAMES):
        demand_data[day_name] = {drink: int(PREDICTED_SALES[drink][i]) for drink in DRINKS}
    
    demand_df = pd.DataFrame(demand_data)
    
    # Display the editor - only editable if use_predicted is False
    edited_demand_df = st.data_editor(
        demand_df, 
        key="demand_editor",
        disabled=use_predicted
    )
    
    # Convert edited data back to the required format if not using predicted
    if not use_predicted:
        for drink in DRINKS:
             manual_sales[drink] = edited_demand_df.loc[drink].values.astype(int)


with input_col2:
    st.header("2. Cost Parameters")
    
    with st.expander("Adjust Costs", expanded=False): # Keep cost adjustments collapsed by default
        st.subheader("Ingredient Costs ($/kg)")
        # Use columns for better layout of cost inputs
        cost_cols = st.columns(len(INGREDIENTS))
        current_standard_costs = {}
        for i, ing in enumerate(INGREDIENTS):
            with cost_cols[i]:
                current_standard_costs[ing] = st.number_input(
                    ing,
                    min_value=0.0,
                    value=DEFAULT_STANDARD_COSTS[ing],
                    step=0.1,
                    format="%.2f",
                    key=f"cost_{ing}"
                )

        st.subheader("Thursday Discount")
        current_thursday_discount_rate = st.slider(
            "Discount Rate (%)",
            min_value=0.0,
            max_value=100.0,
            value=DEFAULT_THURSDAY_DISCOUNT_RATE * 100, # Display as percentage
            step=1.0,
            key="discount_rate"
        ) / 100.0 # Convert back to decimal for calculation

        st.subheader("Holding Costs ($/kg/day)")
        holding_cost_cols = st.columns(len(INGREDIENTS))
        current_holding_costs = {}
        for i, ing in enumerate(INGREDIENTS):
            with holding_cost_cols[i]:
                current_holding_costs[ing] = st.number_input(
                    ing,
                    min_value=0.0,
                    value=DEFAULT_HOLDING_COSTS[ing],
                    step=0.1,
                    format="%.2f",
                    key=f"holding_{ing}"
                )

# --- Use default costs if expander is not used or values haven't been set yet ---
# (Streamlit retains state, so inputs inside expander will be used once set)
# Retrieve current cost values (defaults are used initially)
current_standard_costs = {ing: st.session_state.get(f"cost_{ing}", DEFAULT_STANDARD_COSTS[ing]) for ing in INGREDIENTS}
current_thursday_discount_rate = st.session_state.get("discount_rate", DEFAULT_THURSDAY_DISCOUNT_RATE * 100) / 100.0
current_holding_costs = {ing: st.session_state.get(f"holding_{ing}", DEFAULT_HOLDING_COSTS[ing]) for ing in INGREDIENTS}


# Determine which sales data to use outside the columns
if use_predicted:
    sales_to_use = PREDICTED_SALES
    # Display the predicted sales being used
    st.sidebar.info("Using pre-defined predicted sales data.")
    # st.sidebar.dataframe(pd.DataFrame({drink: sales_to_use[drink] for drink in DRINKS}, index=DAY_NAMES).T) 
else:
    sales_to_use = manual_sales
    st.sidebar.info("Using manually entered sales data.")
    # st.sidebar.dataframe(edited_demand_df) # Show the edited df in sidebar


# --- Calculation Trigger ---
st.divider() # Add a visual separator
st.header("3. Generate Ordering Plan")

if st.button("Calculate Optimal Ordering Plan", key="calculate_button"):
    # 1. Calculate ingredient demand based on selected sales data
    # Ensure sales_to_use is correctly formatted if using manual data from data_editor
    if not use_predicted:
        sales_data_for_calc = {drink: edited_demand_df.loc[drink].values.astype(int) for drink in DRINKS}
    else:
        sales_data_for_calc = sales_to_use

    ingredient_demand = calculate_demand_from_sales(sales_data_for_calc)

    # 2. Solve the LP problem using current cost parameters from the UI
    with st.spinner("Calculating optimal plan..."):
        results = solve_ordering_plan(
            ingredient_demand,
            current_standard_costs,
            current_thursday_discount_rate,
            current_holding_costs
        )

    # 3. Display Results
    st.subheader("4. Results") # Renumbered section
    if results["status"] == 'Optimal':
        st.success("Optimal solution found!")
        st.metric(label="Minimum Total Cost", value=f"${results['total_cost']:.2f}")

        st.markdown("#### Optimal Ordering Quantities (kg)")
        # Use st.dataframe for better table rendering
        st.dataframe(results["order_plan_df"].style.format("{:.2f}").highlight_max(axis=1, color='lightgreen')) 

        st.markdown("#### End-of-Day Inventory Levels (kg)")
        st.dataframe(results["inventory_levels_df"].style.format("{:.2f}"))

    elif results["status"] == 'TimeLimitReached':
         st.warning(f"Solver stopped due to time limit. The solution might not be optimal.")
         # Optionally display the potentially suboptimal results if needed
         if "total_cost" in results:
             st.metric(label="Current Best Cost (Suboptimal)", value=f"${results['total_cost']:.2f}")
             st.markdown("#### Current Order Plan (kg)")
             st.dataframe(results["order_plan_df"].style.format("{:.2f}")) 
             st.markdown("#### Current Inventory Levels (kg)")
             st.dataframe(results["inventory_levels_df"].style.format("{:.2f}"))

    else:
        st.error(f"Solver Status: {results['status']}. Could not find an optimal solution.")
        st.warning("Check if demand is feasible with ordering constraints and costs.")

else:
    st.info("Adjust demand and/or cost parameters, then click the button to calculate the plan.") # Updated info message

# Add some explanation in the sidebar
st.sidebar.divider()
st.sidebar.header("About")
st.sidebar.markdown("""
This application calculates the optimal weekly material ordering plan for a coffee shop
to minimize total costs (ordering + holding) based on demand forecasts and cost parameters.

**Features:**
- Input daily sales demand (manual or predicted).
- Adjust ingredient costs, Thursday discount, and holding costs (in expander).
- Calculates and displays the optimal order quantities and inventory levels.
- Advanced features for product management, seasonal demand, expiry constraints and more.
""")

# --- Extension Features (Problem 6) ---
st.divider()
st.header("5. Advanced Features")
tab_new_drink, tab_seasonal, tab_ordering_policy, tab_expiry, tab_stockout, tab_sensitivity = st.tabs([
    "New Product Design", 
    "Seasonal Demand", 
    "Ordering Policy",
    "Expiry Constraints", 
    "Stockout Analysis",
    "Sensitivity Analysis"
])

# --- Tab 1: New Product Design ---
with tab_new_drink:
    st.subheader("Add New Drink Product")
    st.write("Design a new drink by defining its ingredient recipe.")
    
    col1, col2 = st.columns([2, 3])
    
    with col1:
        new_drink_name = st.text_input("New Drink Name", "")
        
    with col2:
        st.write("Recipe (kg per drink):")
        recipe_cols = st.columns(len(INGREDIENTS))
        new_recipe = {}
        for i, ing in enumerate(INGREDIENTS):
            with recipe_cols[i]:
                new_recipe[ing] = st.number_input(
                    f"{ing}",
                    min_value=0.000,
                    value=0.010,
                    step=0.001,
                    format="%.3f",
                    key=f"new_recipe_{ing}"
                )
    
    if st.button("Add New Drink", key="add_drink_btn"):
        if new_drink_name.strip():
            success, message = create_new_drink(new_drink_name, new_recipe)
            if success:
                st.success(message)
                # Update the input table to include the new drink
                # Don't directly modify the widget state - use session state flag instead
                if "use_predicted_demand" in st.session_state:
                    # Create a flag to indicate we should rerun with use_predicted_demand=False next time
                    st.session_state["force_manual_input"] = True
                # Add a placeholder default demand for the new drink
                default_demand = np.array([50, 45, 55, 100, 120, 110, 65])  # reasonable default values
                PREDICTED_SALES[new_drink_name] = default_demand
                st.experimental_rerun()  # Rerun to refresh UI with new drink
            else:
                st.error(message)
        else:
            st.error("Please enter a name for the new drink.")
    
    # Display current drinks and recipes
    with st.expander("View Current Drinks and Recipes", expanded=False):
        # 使用 if True 来确保每次展开时都会重新计算最新的饮品列表
        if True:
            recipe_df = pd.DataFrame(index=DRINKS)
            for ing in INGREDIENTS:
                recipe_df[ing] = [KG_PER_DRINK[ing].get(drink, 0.0) for drink in DRINKS]
            st.dataframe(recipe_df.style.format("{:.3f} kg"))
            
            # 显示当前饮品列表，确保用户可以看到最新添加的饮品
            st.write(f"当前饮品列表: {', '.join(DRINKS)}")

# --- Tab 2: Seasonal Demand Adjustments ---
with tab_seasonal:
    st.subheader("Seasonal Demand Adjustment")
    st.write("Adjust daily demand by applying seasonal factors.")
    
    use_seasonal = st.checkbox("Enable Seasonal Adjustment", value=False, key="use_seasonal")
    
    if use_seasonal:
        st.write("Set multiplier factors for each day:")
        seasonal_cols = st.columns(len(DAY_NAMES))
        seasonal_factors = {}
        
        for i, day in enumerate(DAY_NAMES):
            with seasonal_cols[i]:
                seasonal_factors[day] = st.slider(
                    f"{day}", 
                    min_value=0.5, 
                    max_value=2.0, 
                    value=1.0, 
                    step=0.05,
                    key=f"seasonal_{day}"
                )
        
        # Preview the effect
        if st.button("Preview Adjusted Demand", key="preview_seasonal"):
            base_sales = sales_to_use if use_predicted else {drink: edited_demand_df.loc[drink].values for drink in DRINKS}
            adjusted_sales = apply_seasonal_factors(base_sales, seasonal_factors)
            
            # Show before/after comparison
            col1, col2 = st.columns(2)
            with col1:
                st.write("Original Demand:")
                original_df = pd.DataFrame({drink: base_sales[drink] for drink in base_sales}, index=DAY_NAMES).T
                st.dataframe(original_df)
            
            with col2:
                st.write("Adjusted Demand:")
                adjusted_df = pd.DataFrame({drink: adjusted_sales[drink] for drink in adjusted_sales}, index=DAY_NAMES).T
                st.dataframe(adjusted_df.style.background_gradient(axis=1, cmap="YlGn"))
    else:
        st.info("Seasonal adjustment is disabled. Enable it to apply day-specific demand multipliers.")

# --- Tab 3: Ordering Policy ---
with tab_ordering_policy:
    st.subheader("Ordering Policy Optimization")
    st.write("Adjust ordering constraints to explore different policies.")
    
    policy_type = st.radio(
        "Select Ordering Policy",
        ["Standard (Tue & Fri No Orders)", "Custom Ordering Days", "Minimum Order Quantities"],
        key="policy_type"
    )
    
    ordering_days = None
    min_order_quantities = None
    
    if policy_type == "Custom Ordering Days":
        st.write("Select days when ordering is allowed:")
        day_cols = st.columns(len(DAY_NAMES))
        ordering_days = []
        
        for i, day in enumerate(DAY_NAMES):
            with day_cols[i]:
                if st.checkbox(day, value=(i not in NO_ORDER_DAYS), key=f"order_day_{i}"):
                    ordering_days.append(i)
        
        if not ordering_days:
            st.warning("You must select at least one ordering day.")
    
    elif policy_type == "Minimum Order Quantities":
        st.write("Set minimum order quantities for each ingredient (kg):")
        min_cols = st.columns(len(INGREDIENTS))
        min_order_quantities = {}
        
        for i, ing in enumerate(INGREDIENTS):
            with min_cols[i]:
                min_order_quantities[ing] = st.number_input(
                    ing, 
                    min_value=0.0, 
                    value=0.0, 
                    step=0.5,
                    key=f"min_order_{ing}"
                )

# --- Tab 4: Expiry Constraints ---
with tab_expiry:
    st.subheader("Ingredient Expiry Constraints")
    st.write("Set expiry periods for ingredients to prevent waste.")
    
    use_expiry = st.checkbox("Enable Expiry Constraints", value=False, key="use_expiry")
    
    if use_expiry:
        st.write("Set expiry period (days) for each ingredient:")
        expiry_cols = st.columns(len(INGREDIENTS))
        expiry_days = {}
        
        for i, ing in enumerate(INGREDIENTS):
            with expiry_cols[i]:
                expiry_days[ing] = st.slider(
                    ing, 
                    min_value=1, 
                    max_value=7, 
                    value=7,  # Default to 7 days (full week)
                    key=f"expiry_{ing}"
                )
    else:
        expiry_days = None
        st.info("Expiry constraints are disabled. Enable to limit how long ingredients can be stored.")

# --- Tab 5: Stockout Analysis ---
with tab_stockout:
    st.subheader("Stockout Cost Analysis")
    st.write("Include stockout costs to analyze trade-offs between stockouts and inventory.")
    
    use_stockout = st.checkbox("Consider Stockout Costs", value=False, key="use_stockout")
    
    if use_stockout:
        st.write("Set stockout penalty costs ($/kg/day):")
        stockout_cols = st.columns(len(INGREDIENTS))
        stockout_costs = {}
        
        for i, ing in enumerate(INGREDIENTS):
            with stockout_cols[i]:
                default_stockout = current_holding_costs[ing] * 10  # Default to 10x holding cost
                stockout_costs[ing] = st.number_input(
                    ing, 
                    min_value=0.0, 
                    value=default_stockout, 
                    step=1.0,
                    format="%.1f",
                    key=f"stockout_{ing}"
                )
    else:
        stockout_costs = None
        st.info("Stockout costs are disabled. Enable to allow the model to consider stockout penalties.")

# --- Tab 6: Sensitivity Analysis ---
with tab_sensitivity:
    st.subheader("Sensitivity Analysis")
    st.write("Analyze how changes in key parameters affect the optimal cost.")
    
    analysis_parameter = st.selectbox(
        "Select Parameter to Analyze",
        ["Thursday Discount Rate", "Holding Cost Factor", "Demand Factor"],
        key="analysis_param"
    )
    
    if analysis_parameter == "Thursday Discount Rate":
        values = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
        st.write(f"Analyzing discount rates: {', '.join([f'{v*100:.0f}%' for v in values])}")
        x_label = "Thursday Discount Rate"
        param_name = "thursday_discount"
        
    elif analysis_parameter == "Holding Cost Factor":
        values = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
        st.write(f"Analyzing holding cost factors: {', '.join([str(v) for v in values])}")
        x_label = "Holding Cost Factor"
        param_name = "holding_cost_factor"
        
    else:  # Demand Factor
        values = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        st.write(f"Analyzing demand factors: {', '.join([str(v) for v in values])}")
        x_label = "Demand Factor"
        param_name = "demand_factor"
    
    if st.button("Run Sensitivity Analysis", key="run_sensitivity"):
        with st.spinner("Running analysis..."):
            # Calculate base demand from sales data
            if use_predicted:
                sales_data_for_calc = PREDICTED_SALES
            else:
                sales_data_for_calc = {drink: edited_demand_df.loc[drink].values.astype(int) for drink in DRINKS}
                
            # Apply seasonal adjustments if enabled
            if "use_seasonal" in st.session_state and st.session_state.use_seasonal:
                seasonal_factors_to_use = {day: st.session_state.get(f"seasonal_{day}", 1.0) for day in DAY_NAMES}
                sales_data_for_calc = apply_seasonal_factors(sales_data_for_calc, seasonal_factors_to_use)
                
            base_demand = calculate_demand_from_sales(sales_data_for_calc)
            
            # Run sensitivity analysis
            sensitivity_results = run_sensitivity_analysis(
                base_demand, 
                current_standard_costs,
                param_name,
                values,
                current_thursday_discount_rate if param_name == "thursday_discount" else None,
                current_holding_costs
            )
            
            # Plot results
            valid_results = [(x, y) for x, y in sensitivity_results if y is not None]
            if valid_results:
                x_vals, y_vals = zip(*valid_results)
                
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.plot(x_vals, y_vals, marker='o', linestyle='-', linewidth=2, markersize=8)
                
                if param_name == "thursday_discount":
                    ax.set_xlabel("Thursday Discount Rate")
                    x_tick_labels = [f"{x*100:.0f}%" for x in x_vals]
                    ax.set_xticklabels(x_tick_labels)
                else:
                    ax.set_xlabel(x_label)
                    
                ax.set_ylabel("Total Cost ($)")
                ax.set_title(f"Sensitivity Analysis: Impact of {x_label} on Total Cost")
                ax.grid(True, linestyle='--', alpha=0.7)
                
                # Add data labels
                for x, y in zip(x_vals, y_vals):
                    ax.annotate(f"${y:.2f}", 
                               (x, y),
                               textcoords="offset points",
                               xytext=(0,10), 
                               ha='center')
                
                st.pyplot(fig)
                
                # Show data table
                result_df = pd.DataFrame({
                    x_label: x_vals,
                    "Total Cost": [f"${y:.2f}" for y in y_vals]
                })
                st.dataframe(result_df)
            else:
                st.error("Sensitivity analysis failed to produce valid results. Try different parameter values.")
    else:
        st.info("Click 'Run Sensitivity Analysis' to see how the selected parameter affects total cost.")

# --- Enhanced Calculate Button with Advanced Features ---
st.divider()
st.header("6. Calculate with Advanced Features")

if st.button("Calculate Enhanced Ordering Plan", type="primary", key="enhanced_calculate"):
    # Determine which sales data to use
    if use_predicted:
        sales_data_for_calc = PREDICTED_SALES.copy()
    else:
        sales_data_for_calc = {drink: edited_demand_df.loc[drink].values.astype(int) for drink in DRINKS}
    
    # Apply seasonal factors if enabled
    if "use_seasonal" in st.session_state and st.session_state.use_seasonal:
        seasonal_factors_to_use = {day: st.session_state.get(f"seasonal_{day}", 1.0) for day in DAY_NAMES}
        sales_data_for_calc = apply_seasonal_factors(sales_data_for_calc, seasonal_factors_to_use)
    
    # Calculate ingredient demand
    ingredient_demand = calculate_demand_from_sales(sales_data_for_calc)
    
    # Get policy settings
    policy_type = st.session_state.get("policy_type", "Standard (Tue & Fri No Orders)")
    
    ordering_days_to_use = None
    if policy_type == "Custom Ordering Days":
        ordering_days_to_use = []
        for i, day in enumerate(DAY_NAMES):
            if st.session_state.get(f"order_day_{i}", i not in NO_ORDER_DAYS):
                ordering_days_to_use.append(i)
    
    min_order_quantities_to_use = None
    if policy_type == "Minimum Order Quantities":
        min_order_quantities_to_use = {ing: st.session_state.get(f"min_order_{ing}", 0.0) for ing in INGREDIENTS}
    
    # Get expiry settings
    expiry_days_to_use = None
    if "use_expiry" in st.session_state and st.session_state.use_expiry:
        expiry_days_to_use = {ing: st.session_state.get(f"expiry_{ing}", 7) for ing in INGREDIENTS}
    
    # Get stockout settings
    stockout_costs_to_use = None
    if "use_stockout" in st.session_state and st.session_state.use_stockout:
        stockout_costs_to_use = {ing: st.session_state.get(f"stockout_{ing}", 0.0) for ing in INGREDIENTS}
    
    # Solve enhanced model
    with st.spinner("Calculating enhanced ordering plan..."):
        enhanced_results = enhanced_solve_ordering_plan(
            ingredient_demand,
            current_standard_costs,
            current_thursday_discount_rate,
            current_holding_costs,
            expiry_days=expiry_days_to_use,
            min_order_quantities=min_order_quantities_to_use,
            stockout_costs=stockout_costs_to_use,
            ordering_days=ordering_days_to_use
        )
    
    # Display Results
    st.subheader("7. Enhanced Results")
    
    # Display active constraints
    active_constraints = []
    if policy_type != "Standard (Tue & Fri No Orders)":
        active_constraints.append(f"✓ {policy_type}")
    if "use_expiry" in st.session_state and st.session_state.use_expiry:
        active_constraints.append("✓ Expiry Constraints")
    if "use_stockout" in st.session_state and st.session_state.use_stockout:
        active_constraints.append("✓ Stockout Costs")
    if "use_seasonal" in st.session_state and st.session_state.use_seasonal:
        active_constraints.append("✓ Seasonal Adjustment")
    
    if active_constraints:
        st.write("Active Advanced Features:", ", ".join(active_constraints))
    
    # Display results
    if enhanced_results["status"] == 'Optimal':
        st.success("Optimal enhanced solution found!")
        st.metric(label="Minimum Total Cost", value=f"${enhanced_results['total_cost']:.2f}")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### Optimal Ordering Quantities (kg)")
            st.dataframe(enhanced_results["order_plan_df"].style.format("{:.2f}").highlight_max(axis=1, color='lightgreen'))
        
        with col2:
            st.markdown("#### End-of-Day Inventory Levels (kg)")
            st.dataframe(enhanced_results["inventory_levels_df"].style.format("{:.2f}"))
        
        # Show stockout information if applicable
        if "stockout_levels_df" in enhanced_results:
            st.markdown("#### Stockout Levels (kg)")
            stockout_df = enhanced_results["stockout_levels_df"]
            if stockout_df.values.sum() > 0:
                st.dataframe(stockout_df.style.format("{:.2f}").highlight_max(axis=1, color='pink'))
                
                # Calculate stockout cost
                stockout_cost = sum(
                    stockout_costs_to_use[ing] * stockout_df.loc[ing, day] 
                    for ing in INGREDIENTS 
                    for day in DAY_NAMES 
                    if stockout_df.loc[ing, day] > 0
                )
                st.metric("Total Stockout Cost", f"${stockout_cost:.2f}")
            else:
                st.info("No stockouts in the optimal solution.")
        
        # Calculate cost breakdown
        if st.checkbox("Show Cost Breakdown", key="show_cost_breakdown"):
            order_costs = {}
            inventory_costs = {}
            
            for ing in INGREDIENTS:
                order_costs[ing] = 0
                for day_idx, day in enumerate(DAY_NAMES):
                    if enhanced_results["order_plan_df"].loc[ing, day] > 0:
                        cost_multiplier = 1.0 if day_idx != 3 else (1.0 - current_thursday_discount_rate)
                        order_costs[ing] += enhanced_results["order_plan_df"].loc[ing, day] * current_standard_costs[ing] * cost_multiplier
                
                inventory_costs[ing] = 0
                for day in DAY_NAMES:
                    inventory_costs[ing] += enhanced_results["inventory_levels_df"].loc[ing, day] * current_holding_costs[ing]
            
            total_order_cost = sum(order_costs.values())
            total_inventory_cost = sum(inventory_costs.values())
            
            # Prepare data for pie chart
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            
            # Cost type breakdown
            ax1.pie([total_order_cost, total_inventory_cost], 
                   labels=['Order Cost', 'Holding Cost'],
                   autopct='%1.1f%%',
                   colors=['#ff9999','#66b3ff'])
            ax1.set_title('Cost Type Breakdown')
            
            # Ingredient cost breakdown
            ing_total_costs = {}
            for ing in INGREDIENTS:
                ing_total_costs[ing] = order_costs[ing] + inventory_costs[ing]
            
            ax2.pie(ing_total_costs.values(), 
                   labels=ing_total_costs.keys(),
                   autopct='%1.1f%%',
                   colors=['#ff9999','#66b3ff','#99ff99','#ffcc99'])
            ax2.set_title('Cost by Ingredient')
            
            plt.tight_layout()
            st.pyplot(fig)
            
            # Cost breakdown table
            cost_data = {
                'Ingredient': INGREDIENTS,
                'Order Cost ($)': [order_costs[ing] for ing in INGREDIENTS],
                'Holding Cost ($)': [inventory_costs[ing] for ing in INGREDIENTS],
                'Total Cost ($)': [order_costs[ing] + inventory_costs[ing] for ing in INGREDIENTS]
            }
            cost_df = pd.DataFrame(cost_data)
            cost_df.loc['Total'] = ['', sum(cost_df['Order Cost ($)']), sum(cost_df['Holding Cost ($)']), sum(cost_df['Total Cost ($)'])]
            
            st.dataframe(cost_df.style.format({
                'Order Cost ($)': '${:.2f}',
                'Holding Cost ($)': '${:.2f}',
                'Total Cost ($)': '${:.2f}'
            }))
            
    elif enhanced_results["status"] == 'TimeLimitReached':
        st.warning(f"Solver stopped due to time limit. The solution might not be optimal.")
        if "total_cost" in enhanced_results:
            st.metric(label="Current Best Cost (Suboptimal)", value=f"${enhanced_results['total_cost']:.2f}")
            st.markdown("#### Current Order Plan (kg)")
            st.dataframe(enhanced_results["order_plan_df"].style.format("{:.2f}"))
            st.markdown("#### Current Inventory Levels (kg)")
            st.dataframe(enhanced_results["inventory_levels_df"].style.format("{:.2f}"))
    else:
        st.error(f"Solver Status: {enhanced_results['status']}. Could not find an optimal solution.")
        st.warning("Check if your constraints are feasible. Try relaxing some constraints.")
