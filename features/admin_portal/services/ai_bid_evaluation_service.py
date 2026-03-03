# src/features/admin_portal/services/ai_bid_evaluation_service.py

import json
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger
from ....common import llm_service
from ....core.ai_extractor import AIExtractor
import traceback
import re

logger = get_logger(__name__)

class AIBidEvaluationService:
    """
    Service for AI-powered evaluation of supplier bids
    Evaluates bids based on:
    - Price competitiveness
    - Delivery readiness (vs required date)
    - Quantity fulfillment
    - Discount willingness
    """
    
    def __init__(self):
        self.connection = None
        self.cursor = None
        self.ai_extractor = AIExtractor()
        self.model_name = "ibm/granite-3-8b-instruct"
        self.params = {
            "decoding_method": "greedy",
            "max_new_tokens": 1000,
            "temperature": 0.1,
            "top_p": 0.9
        }
    
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
    
    def evaluate_bid(self, mapping_id: int) -> Dict[str, Any]:
        """
        Main method to evaluate a single bid using AI
        """
        try:
            # Get bid details with RFQ information
            bid_data = self._get_bid_details(mapping_id)
            if not bid_data:
                return {
                    "status": "error",
                    "message": "Bid not found"
                }
            
            # Calculate quantitative metrics
            metrics = self._calculate_metrics(bid_data)
            
            # Generate AI evaluation
            ai_evaluation = self._generate_ai_evaluation(bid_data, metrics)
            
            # Calculate overall score
            overall_score = self._calculate_overall_score(metrics, ai_evaluation)
            
            # Store evaluation results
            evaluation_id = self._store_evaluation(
                mapping_id, 
                metrics, 
                ai_evaluation, 
                overall_score
            )
            
            # FIXED: Access rfq_id from the top level of bid_data, not from rfq_info
            return {
                "status": "success",
                "mapping_id": mapping_id,
                "supplier_name": bid_data['supplier_info']['company_name'],
                "rfq_id": bid_data['rfq_id'],  # Changed from bid_data['rfq_info']['rfq_id']
                "evaluation_id": evaluation_id,
                "metrics": metrics,
                "ai_analysis": ai_evaluation,
                "overall_score": overall_score,
                "recommendation": self._get_recommendation(overall_score)
            }
            
        except Exception as e:
            logger.error(f"Error evaluating bid: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _get_bid_details(self, mapping_id: int) -> Optional[Dict[str, Any]]:
        """Get complete bid details with RFQ information"""
        try:
            self.cursor.execute("""
                SELECT 
                    rs.mapping_id,
                    rs.rfq_id,
                    rs.supplier_id,
                    rs.response_details,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.submitted_at,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    h.required_date,
                    h.delivery_deadline,
                    h.total_budget as rfq_budget,
                    h.currency as rfq_currency
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return None
            
            # Parse response_details
            try:
                bid_data = json.loads(row[3]) if row[3] else {}
            except:
                bid_data = {}
            
            # Get RFQ line items for comparison - FIXED: removed required_by_date
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    quantity,
                    unit_price,
                    total_price
                    -- removed required_by_date as it doesn't exist
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (row[1],))
            
            rfq_items = []
            for item in self.cursor.fetchall():
                rfq_items.append({
                    "line_number": item[0],
                    "category": item[1],
                    "brand": item[2],
                    "quantity": float(item[3]) if item[3] else 0,
                    "estimated_unit_price": float(item[4]) if item[4] else None,
                    "estimated_total_price": float(item[5]) if item[5] else None
                    # removed required_by_date
                })
            
            return {
                "mapping_id": row[0],
                "rfq_id": row[1],
                "supplier_id": row[2],
                "response_details": bid_data,
                "quotation_amount": float(row[4]) if row[4] else 0,
                "quotation_currency": row[5],
                "submitted_at": row[6].isoformat() if row[6] else None,
                "supplier_info": {
                    "company_name": row[7],
                    "contact_person": row[8],
                    "email": row[9]
                },
                "rfq_info": {
                    "required_date": row[10].isoformat() if row[10] else None,
                    "delivery_deadline": row[11].isoformat() if row[11] else None,
                    "rfq_budget": float(row[12]) if row[12] else 0,
                    "rfq_currency": row[13]
                },
                "rfq_items": rfq_items
            }
            
        except Exception as e:
            logger.error(f"Error getting bid details: {str(e)}")
            return None
    
    def _calculate_metrics(self, bid_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate quantitative metrics for the bid
        """
        metrics = {
            "price_score": 0,
            "delivery_readiness_score": 0,
            "quantity_fulfillment_score": 0,
            "discount_readiness_score": 0,
            "details": {}
        }
        
        rfq_items = bid_data.get('rfq_items', [])
        quotations = bid_data.get('response_details', {}).get('quotations', [])
        
        # Create map of quotations by line number
        quote_map = {}
        for quote in quotations:
            line_num = quote.get('line_number')
            if line_num:
                quote_map[line_num] = quote
        
        # Calculate per-item metrics
        total_items = len(rfq_items)
        if total_items == 0:
            return metrics
        
        total_price_score = 0
        total_delivery_score = 0
        total_quantity_score = 0
        total_discount_score = 0
        
        items_evaluated = []
        
        for rfq_item in rfq_items:
            line_num = rfq_item['line_number']
            quote = quote_map.get(line_num, {})
            offered_products = quote.get('offered_products', [])
            
            # Calculate metrics for this item
            item_metrics = self._evaluate_single_item(rfq_item, quote, offered_products, bid_data)
            
            total_price_score += item_metrics['price_score']
            total_delivery_score += item_metrics['delivery_score']
            total_quantity_score += item_metrics['quantity_score']
            total_discount_score += item_metrics['discount_score']
            
            items_evaluated.append({
                "line_number": line_num,
                "category": rfq_item['category'],
                "metrics": item_metrics
            })
        
        # Calculate averages
        metrics['price_score'] = round(total_price_score / total_items, 2)
        metrics['delivery_readiness_score'] = round(total_delivery_score / total_items, 2)
        metrics['quantity_fulfillment_score'] = round(total_quantity_score / total_items, 2)
        metrics['discount_readiness_score'] = round(total_discount_score / total_items, 2)
        
        # Overall bid metrics
        metrics['details'] = {
            "items_evaluated": items_evaluated,
            "total_quoted_amount": bid_data.get('quotation_amount', 0),
            "rfq_budget": bid_data['rfq_info'].get('rfq_budget', 0),
            "budget_comparison": self._calculate_budget_comparison(
                bid_data.get('quotation_amount', 0),
                bid_data['rfq_info'].get('rfq_budget', 0)
            )
        }
        
        return metrics
    
    def _evaluate_single_item(self, rfq_item: Dict, quote: Dict, offered_products: List, bid_data: Dict) -> Dict[str, float]:
        """
        Evaluate metrics for a single line item
        """
        rfq_quantity = rfq_item.get('quantity', 0)
        rfq_estimated_price = rfq_item.get('estimated_total_price', 0)
        
        # Price Score (0-100)
        price_score = 50  # Default middle score
        if offered_products and rfq_estimated_price and rfq_estimated_price > 0:
            total_quoted = sum(p.get('total_price', 0) for p in offered_products)
            price_ratio = total_quoted / rfq_estimated_price
            
            # Score based on price comparison
            if price_ratio <= 0.9:  # 10% below estimate
                price_score = 100
            elif price_ratio <= 1.0:  # At or below estimate
                price_score = 90
            elif price_ratio <= 1.1:  # Up to 10% above
                price_score = 70
            elif price_ratio <= 1.2:  # 10-20% above
                price_score = 50
            elif price_ratio <= 1.5:  # 20-50% above
                price_score = 30
            else:  # >50% above
                price_score = 10
        
        # Quantity Fulfillment Score (0-100)
        quantity_score = 0
        if rfq_quantity > 0:
            quoted_quantity = sum(p.get('quantity', 0) for p in offered_products)
            quantity_ratio = quoted_quantity / rfq_quantity if rfq_quantity > 0 else 0
            
            if quantity_ratio >= 1.0:
                quantity_score = 100
            elif quantity_ratio >= 0.8:
                quantity_score = 80
            elif quantity_ratio >= 0.5:
                quantity_score = 60
            elif quantity_ratio >= 0.25:
                quantity_score = 40
            elif quantity_ratio > 0:
                quantity_score = 20
            else:
                quantity_score = 0
        
        # Delivery Readiness Score (0-100)
        delivery_score = 50  # Default
        if offered_products:
            # Check if any product has delivery time from the bid data
            delivery_times = []
            for product in offered_products:
                # Check for delivery_time_days in the product data
                if product.get('delivery_time_days'):
                    delivery_times.append(product['delivery_time_days'])
                # Also check for delivery_date or estimated_delivery
                elif product.get('delivery_date'):
                    # You could calculate days from now to delivery date
                    pass
            
            if delivery_times:
                # Use the shortest delivery time
                min_delivery_days = min(delivery_times)
                
                # Score based on delivery time (lower is better)
                if min_delivery_days <= 7:
                    delivery_score = 100
                elif min_delivery_days <= 14:
                    delivery_score = 80
                elif min_delivery_days <= 21:
                    delivery_score = 60
                elif min_delivery_days <= 30:
                    delivery_score = 40
                else:
                    delivery_score = 20
            else:
                # If no delivery time provided, check against RFQ required date
                required_date = bid_data.get('rfq_info', {}).get('required_date')
                if required_date:
                    # You could calculate days until required date
                    # For now, use a moderate score
                    delivery_score = 60
        
        # Discount Readiness Score (0-100)
        discount_score = 30  # Default
        if offered_products:
            # Check for discount indicators in product data or notes
            has_discount = False
            
            # Look for discount fields
            for product in offered_products:
                if product.get('discount_percentage') and product['discount_percentage'] > 0:
                    has_discount = True
                    discount_pct = product['discount_percentage']
                    if discount_pct >= 15:
                        discount_score = 100
                    elif discount_pct >= 10:
                        discount_score = 80
                    elif discount_pct >= 5:
                        discount_score = 60
                    break
            
            # Check notes for discount keywords
            notes = quote.get('notes', '') or bid_data.get('response_details', {}).get('summary', {}).get('notes', '')
            if not has_discount and notes:
                discount_keywords = ['discount', 'promotion', 'special offer', 'price reduction', 'volume discount']
                if any(keyword in notes.lower() for keyword in discount_keywords):
                    discount_score = 70
        
        return {
            "price_score": price_score,
            "delivery_score": delivery_score,
            "quantity_score": quantity_score,
            "discount_score": discount_score
        }
    
    def _calculate_budget_comparison(self, quoted_amount: float, budget_amount: float) -> Dict:
        """Compare quoted amount with RFQ budget"""
        if not budget_amount or budget_amount == 0:
            return {"status": "unknown", "difference": 0}
        
        difference = quoted_amount - budget_amount
        percentage = (difference / budget_amount) * 100 if budget_amount > 0 else 0
        
        status = "under_budget" if difference < 0 else "over_budget" if difference > 0 else "on_budget"
        
        return {
            "status": status,
            "difference": abs(difference),
            "percentage": round(percentage, 2),
            "quoted": quoted_amount,
            "budget": budget_amount
        }
    
    def _generate_ai_evaluation(self, bid_data: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use AI to generate qualitative evaluation of the bid
        Now returns the raw AI response directly
        """
        try:
            # Prepare data for AI analysis
            analysis_data = self._prepare_analysis_data(bid_data, metrics)
            
            # Create the system prompt for bid evaluation
            system_prompt = self._create_evaluation_system_prompt()
            
            # Create the user prompt with the actual data
            user_prompt = self._create_evaluation_user_prompt(analysis_data)
            
            # Combine for the full prompt
            full_prompt = f"""{system_prompt}

    Supplier Bid Data:
    {user_prompt}

    Remember: Return ONLY the JSON object, no other text."""
            
            if llm_service is None:
                logger.warning("LLM service not available for bid evaluation")
                return self._get_default_evaluation()
            
            try:
                # Use llm_service.invoke_with_recovery
                response = llm_service.invoke_with_recovery(
                    model_name=self.model_name,
                    params=self.params,
                    prompt=full_prompt,
                    max_retries=1
                )
                
                # Clean and parse the JSON
                json_data = self._clean_and_parse_json(response)
                
                logger.info(f"Successfully generated AI evaluation for {bid_data['supplier_info']['company_name']}")
                
                # Return the raw JSON data directly - no restructuring needed!
                return json_data
                    
            except Exception as e:
                logger.error(f"LLM evaluation failed: {str(e)}")
                return self._get_default_evaluation()
            
        except Exception as e:
            logger.error(f"Error generating AI evaluation: {str(e)}")
            return self._get_default_evaluation()
    
    def _create_evaluation_system_prompt(self) -> str:
        """Create the system prompt for bid evaluation (similar to EXTRACTION_SYSTEM_PROMPT pattern)"""
        return """You are an expert procurement analyst specializing in bid evaluation. 
Your task is to analyze supplier bid data and provide structured insights.

Analyze the supplier bid data and provide detailed insights on:
1. Price competitiveness and value for money
2. Supplier's ability to meet delivery deadlines
3. Quantity fulfillment capability
4. Potential for negotiation/discounts
5. Overall risk assessment

Be objective, data-driven, and provide actionable insights.

You must respond with a valid JSON object containing your analysis.
Do not include any explanatory text outside the JSON object."""
    
    def _create_evaluation_user_prompt(self, data: Dict) -> str:
        """Create the user prompt with the bid data"""
        # Format quotations for better readability
        quotations_summary = []
        for quote in data.get('quotations', []):
            line_num = quote.get('line_number')
            products = quote.get('offered_products', [])
            product_count = len(products)
            total_qty = sum(p.get('quantity', 0) for p in products)
            total_price = sum(p.get('total_price', 0) for p in products)
            
            quotations_summary.append({
                "line_number": line_num,
                "products_offered": product_count,
                "total_quantity": total_qty,
                "total_price": total_price
            })
        
        return f"""
    Supplier: {data['supplier']}
    Total Quoted: {data['currency']} {data['total_quoted']:,.2f}
    RFQ Budget: {data['currency']} {data['rfq_budget']:,.2f}
    Required Date: {data['required_date']}
    Submission Date: {data['submitted_at']}

    Quantitative Metrics:
    - Price Score: {data['metrics']['price_score']}/100
    - Delivery Readiness: {data['metrics']['delivery_readiness_score']}/100
    - Quantity Fulfillment: {data['metrics']['quantity_fulfillment_score']}/100
    - Discount Readiness: {data['metrics']['discount_readiness_score']}/100

    Quotations Summary:
    {json.dumps(quotations_summary, indent=2)}

    Full Quotations Data:
    {json.dumps(data['quotations'], indent=2)}

    Summary Information:
    {json.dumps(data['summary'], indent=2)}

    Based on this data, provide a comprehensive evaluation with the following structure:
    - price_analysis: Object with price_score, value_for_money, price_competitiveness, price_competitiveness_analysis
    - delivery_analysis: Object with delivery_readiness, delivery_timeline_capability, delivery_timeline_analysis
    - quantity_analysis: Object with quantity_fulfillment, quantity_fulfillment_capability, quantity_fulfillment_analysis
    - discount_potential: Object with discount_readiness, discount_opportunities, discount_analysis
    - risk_assessment: Object with overall_risk, risk_factors (list), risk_mitigation_strategies
    - strengths: List of strengths
    - weaknesses: List of weaknesses
    - negotiation_tips: List of negotiation tips

    Return ONLY a valid JSON object with these exact keys.
    """
    
    def _clean_and_parse_json(self, text: str) -> Dict[str, Any]:
        """Clean and parse JSON from AI response - follows pattern from ai_extractor.py"""
        # Remove markdown code blocks
        text = text.replace('```json', '').replace('```', '').strip()
        
        # Look for the first complete JSON object
        brace_count = 0
        start_idx = -1
        end_idx = -1
        
        for i, char in enumerate(text):
            if char == '{':
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx != -1:
                    end_idx = i + 1
                    break
        
        if start_idx != -1 and end_idx != -1:
            json_str = text[start_idx:end_idx]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                raise
        
        # If no JSON object found with brace counting, try regex
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                raise
        
        # If all fails, try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Direct JSON parse failed: {e}")
            raise
    
    def _structure_evaluation(self, json_data: Dict) -> Dict[str, Any]:
        """Structure the AI evaluation response"""
        
        # Initialize with defaults
        evaluation = {
            "price_analysis": "Price analysis not available",
            "delivery_analysis": "Delivery analysis not available",
            "quantity_analysis": "Quantity analysis not available",
            "discount_potential": "Discount potential not available",
            "risk_assessment": "Risk assessment not available",
            "strengths": [],
            "weaknesses": [],
            "negotiation_tips": []
        }
        
        try:
            # Map the AI response structure to our expected format
            if "1. Price competitiveness analysis" in json_data:
                price_data = json_data["1. Price competitiveness analysis"]
                if isinstance(price_data, dict):
                    # Combine analysis text
                    analysis_parts = []
                    if price_data.get("analysis"):
                        analysis_parts.append(price_data["analysis"])
                    if price_data.get("value_for_money"):
                        analysis_parts.append(f"Value for money: {price_data['value_for_money']}")
                    if price_data.get("comparison"):
                        analysis_parts.append(f"Comparison: {price_data['comparison']}")
                    
                    evaluation["price_analysis"] = " | ".join(analysis_parts)
            
            if "2. Delivery timeline assessment" in json_data:
                delivery_data = json_data["2. Delivery timeline assessment"]
                if isinstance(delivery_data, dict):
                    analysis_parts = []
                    if delivery_data.get("analysis"):
                        analysis_parts.append(delivery_data["analysis"])
                    if delivery_data.get("assessment"):
                        analysis_parts.append(delivery_data["assessment"])
                    if delivery_data.get("delivery_time"):
                        analysis_parts.append(f"Delivery time: {delivery_data['delivery_time']}")
                    
                    evaluation["delivery_analysis"] = " | ".join(analysis_parts)
            
            if "3. Quantity fulfillment capability" in json_data:
                quantity_data = json_data["3. Quantity fulfillment capability"]
                if isinstance(quantity_data, dict):
                    analysis_parts = []
                    if quantity_data.get("analysis"):
                        analysis_parts.append(quantity_data["analysis"])
                    if quantity_data.get("assessment"):
                        analysis_parts.append(quantity_data["assessment"])
                    
                    evaluation["quantity_analysis"] = " | ".join(analysis_parts)
            
            if "4. Potential for negotiation/discounts" in json_data:
                discount_data = json_data["4. Potential for negotiation/discounts"]
                if isinstance(discount_data, dict):
                    analysis_parts = []
                    if discount_data.get("analysis"):
                        analysis_parts.append(discount_data["analysis"])
                    
                    evaluation["discount_potential"] = " | ".join(analysis_parts)
            
            if "5. Overall risk assessment" in json_data:
                risk_data = json_data["5. Overall risk assessment"]
                if isinstance(risk_data, dict):
                    analysis_parts = []
                    if risk_data.get("analysis"):
                        analysis_parts.append(risk_data["analysis"])
                    if risk_data.get("risk_score"):
                        analysis_parts.append(f"Risk score: {risk_data['risk_score']}")
                    
                    evaluation["risk_assessment"] = " | ".join(analysis_parts)
            
            # Extract strengths, weaknesses, and negotiation tips
            if "6. Top 3 strengths" in json_data:
                strengths = json_data["6. Top 3 strengths"]
                if isinstance(strengths, list):
                    evaluation["strengths"] = strengths
                elif isinstance(strengths, str):
                    evaluation["strengths"] = [strengths]
            
            if "7. Top 3 weaknesses" in json_data:
                weaknesses = json_data["7. Top 3 weaknesses"]
                if isinstance(weaknesses, list):
                    evaluation["weaknesses"] = weaknesses
                elif isinstance(weaknesses, str):
                    evaluation["weaknesses"] = [weaknesses]
            
            if "8. Negotiation tips" in json_data:
                tips = json_data["8. Negotiation tips"]
                if isinstance(tips, list):
                    evaluation["negotiation_tips"] = tips
                elif isinstance(tips, str):
                    evaluation["negotiation_tips"] = [tips]
            
            # Also try to extract from alternative formats if the above didn't work
            if evaluation["price_analysis"] == "Price analysis not available":
                for key in json_data:
                    if "price" in key.lower() and "analysis" in key.lower():
                        evaluation["price_analysis"] = str(json_data[key])
                        break
            
        except Exception as e:
            logger.error(f"Error structuring evaluation: {str(e)}")
        
        return evaluation
    
    def _get_default_evaluation(self) -> Dict[str, Any]:
        """Return default evaluation when AI fails"""
        return {
            "price_analysis": "Unable to generate AI price analysis",
            "delivery_analysis": "Unable to generate AI delivery analysis",
            "quantity_analysis": "Unable to generate AI quantity analysis",
            "discount_potential": "Unable to generate AI discount analysis",
            "risk_assessment": "Unable to generate AI risk assessment",
            "strengths": ["Unable to identify strengths"],
            "weaknesses": ["Unable to identify weaknesses"],
            "negotiation_tips": ["Unable to generate negotiation tips"]
        }
    
    def _prepare_analysis_data(self, bid_data: Dict, metrics: Dict) -> Dict:
        """Prepare bid data for AI analysis"""
        return {
            "supplier": bid_data['supplier_info']['company_name'],
            "total_quoted": bid_data['quotation_amount'],
            "currency": bid_data['quotation_currency'],
            "rfq_budget": bid_data['rfq_info']['rfq_budget'],
            "required_date": bid_data['rfq_info']['required_date'],
            "submitted_at": bid_data['submitted_at'],
            "metrics": metrics,
            "quotations": bid_data['response_details'].get('quotations', []),
            "summary": bid_data['response_details'].get('summary', {})
        }
    
    def _calculate_overall_score(self, metrics: Dict, ai_evaluation: Dict) -> float:
        """
        Calculate overall weighted score for the bid
        """
        weights = {
            'price': 0.35,
            'delivery': 0.25,
            'quantity': 0.20,
            'discount': 0.20
        }
        
        weighted_score = (
            metrics['price_score'] * weights['price'] +
            metrics['delivery_readiness_score'] * weights['delivery'] +
            metrics['quantity_fulfillment_score'] * weights['quantity'] +
            metrics['discount_readiness_score'] * weights['discount']
        )
        
        return round(weighted_score, 2)
    
    def _get_recommendation(self, score: float) -> str:
        """Get recommendation based on overall score"""
        if score >= 80:
            return "HIGHLY RECOMMENDED"
        elif score >= 60:
            return "RECOMMENDED"
        elif score >= 40:
            return "CONSIDER WITH CAUTION"
        else:
            return "NOT RECOMMENDED"
    
    def _store_evaluation(self, mapping_id: int, metrics: Dict, 
                      ai_evaluation: Dict, overall_score: float) -> int:
        """
        Store evaluation results in database
        """
        try:
            # Check if table exists, create if not
            self.cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='bid_evaluations' AND xtype='U')
                CREATE TABLE [RFQ].[bid_evaluations] (
                    evaluation_id INT IDENTITY(1,1) PRIMARY KEY,
                    mapping_id INT NOT NULL,
                    overall_score DECIMAL(5,2),
                    price_score DECIMAL(5,2),
                    delivery_score DECIMAL(5,2),
                    quantity_score DECIMAL(5,2),
                    discount_score DECIMAL(5,2),
                    ai_analysis NVARCHAR(MAX),
                    recommendation NVARCHAR(50),
                    created_at DATETIME2 DEFAULT GETDATE(),
                    FOREIGN KEY (mapping_id) REFERENCES [RFQ].[rfq_suppliers](mapping_id)
                )
            """)
            self.connection.commit()
            
            # Make sure ai_evaluation is a dict and properly serialized
            if isinstance(ai_evaluation, dict):
                # If it's already a dict, use it directly
                ai_analysis_json = json.dumps(ai_evaluation)
            else:
                # If it's a string, try to parse it first
                try:
                    # If it's a string representation of a dict, convert to dict then to JSON
                    if isinstance(ai_evaluation, str):
                        # Try to parse the string as JSON
                        parsed = json.loads(ai_evaluation)
                        ai_analysis_json = json.dumps(parsed)
                    else:
                        ai_analysis_json = json.dumps(ai_evaluation)
                except:
                    # If parsing fails, store as is
                    ai_analysis_json = json.dumps({"raw_response": str(ai_evaluation)})
            
            # Insert evaluation
            self.cursor.execute("""
                INSERT INTO [RFQ].[bid_evaluations]
                (mapping_id, overall_score, price_score, delivery_score, 
                quantity_score, discount_score, ai_analysis, recommendation, created_at)
                OUTPUT INSERTED.evaluation_id
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, GETDATE())
            """, (
                mapping_id,
                overall_score,
                metrics['price_score'],
                metrics['delivery_readiness_score'],
                metrics['quantity_fulfillment_score'],
                metrics['discount_readiness_score'],
                ai_analysis_json,  # Use the properly formatted JSON
                self._get_recommendation(overall_score)
            ))
            
            evaluation_id = self.cursor.fetchone()[0]
            self.connection.commit()
            
            return evaluation_id
            
        except Exception as e:
            logger.error(f"Error storing evaluation: {str(e)}")
            return 0
    
    def compare_bids(self, rfq_id: str) -> Dict[str, Any]:
        """
        Compare all bids for an RFQ and rank them
        """
        try:
            # Get all suppliers who submitted bids for this RFQ
            self.cursor.execute("""
                SELECT mapping_id, supplier_id, quotation_amount, quotation_currency
                FROM [RFQ].[rfq_suppliers]
                WHERE rfq_id = ? AND quotation_received = 1
            """, (rfq_id,))
            
            bids = self.cursor.fetchall()
            
            if not bids:
                return {
                    "status": "error",
                    "message": "No bids found for this RFQ"
                }
            
            # Evaluate each bid (or get existing evaluations)
            evaluations = []
            for bid in bids:
                mapping_id = bid[0]
                
                # Check if evaluation exists
                self.cursor.execute("""
                    SELECT overall_score, recommendation, created_at
                    FROM [RFQ].[bid_evaluations]
                    WHERE mapping_id = ?
                    ORDER BY created_at DESC
                """, (mapping_id,))
                
                eval_row = self.cursor.fetchone()
                
                if eval_row:
                    # Use existing evaluation
                    evaluations.append({
                        "mapping_id": mapping_id,
                        "supplier_id": bid[1],
                        "amount": float(bid[2]) if bid[2] else 0,
                        "currency": bid[3],
                        "overall_score": float(eval_row[0]) if eval_row[0] else 0,
                        "recommendation": eval_row[1],
                        "evaluated_at": eval_row[2].isoformat() if eval_row[2] else None
                    })
                else:
                    # Create new evaluation
                    eval_result = self.evaluate_bid(mapping_id)
                    if eval_result['status'] == 'success':
                        evaluations.append({
                            "mapping_id": mapping_id,
                            "supplier_id": bid[1],
                            "amount": float(bid[2]) if bid[2] else 0,
                            "currency": bid[3],
                            "overall_score": eval_result['overall_score'],
                            "recommendation": eval_result['recommendation'],
                            "evaluated_at": datetime.now().isoformat()
                        })
            
            # Sort by overall score (highest first)
            evaluations.sort(key=lambda x: x['overall_score'], reverse=True)
            
            # Add ranking
            for i, eval in enumerate(evaluations, 1):
                eval['rank'] = i
            
            # Get supplier names
            for eval in evaluations:
                self.cursor.execute("""
                    SELECT company_name FROM [RFQ].[suppliers]
                    WHERE supplier_id = ?
                """, (eval['supplier_id'],))
                row = self.cursor.fetchone()
                eval['supplier_name'] = row[0] if row else "Unknown"
            
            return {
                "status": "success",
                "rfq_id": rfq_id,
                "total_bids": len(evaluations),
                "ranked_bids": evaluations,
                "comparison_summary": self._generate_comparison_summary(evaluations)
            }
            
        except Exception as e:
            logger.error(f"Error comparing bids: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def _generate_comparison_summary(self, evaluations: List) -> str:
        """Generate a summary of bid comparison"""
        if not evaluations:
            return "No bids to compare"
        
        top_bid = evaluations[0]
        lowest_price = min(evaluations, key=lambda x: x['amount'])
        
        summary = f"Top ranked bid: {top_bid['supplier_name']} with score {top_bid['overall_score']}/100. "
        summary += f"Lowest price: {lowest_price['supplier_name']} at {lowest_price['currency']} {lowest_price['amount']:,.2f}. "
        
        if top_bid['mapping_id'] != lowest_price['mapping_id']:
            summary += "Note: Highest score is not the lowest price, indicating other factors (delivery, quantity, discounts) are significant."
        
        return summary
    
    def get_evaluation_report(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get complete evaluation report for a bid
        """
        try:
            # Get the latest evaluation
            self.cursor.execute("""
                SELECT 
                    e.evaluation_id,
                    e.overall_score,
                    e.price_score,
                    e.delivery_score,
                    e.quantity_score,
                    e.discount_score,
                    e.ai_analysis,
                    e.recommendation,
                    e.created_at,
                    rs.rfq_id,
                    rs.supplier_id,
                    s.company_name,
                    rs.quotation_amount,
                    rs.quotation_currency
                FROM [RFQ].[bid_evaluations] e
                JOIN [RFQ].[rfq_suppliers] rs ON e.mapping_id = rs.mapping_id
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE e.mapping_id = ?
                ORDER BY e.created_at DESC
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                # No evaluation exists, create one
                eval_result = self.evaluate_bid(mapping_id)
                if eval_result['status'] == 'success':
                    return eval_result
                return {"status": "error", "message": "Could not create evaluation"}
            
            # Parse AI analysis - this should now be a proper dict
            try:
                ai_analysis = json.loads(row[6]) if row[6] else {}
                # If it's a string inside (like your current data), try to parse it again
                if isinstance(ai_analysis.get('price_analysis'), str):
                    try:
                        # Attempt to parse nested JSON strings
                        for key in ['price_analysis', 'delivery_analysis', 'quantity_analysis', 
                                'discount_potential', 'risk_assessment']:
                            if key in ai_analysis and isinstance(ai_analysis[key], str):
                                if ai_analysis[key].startswith('{'):
                                    ai_analysis[key] = json.loads(ai_analysis[key])
                    except:
                        pass
            except:
                ai_analysis = {}
            
            return {
                "status": "success",
                "evaluation_id": row[0],
                "mapping_id": mapping_id,
                "rfq_id": row[9],
                "supplier_id": row[10],
                "supplier_name": row[11],
                "quotation": {
                    "amount": float(row[12]) if row[12] else 0,
                    "currency": row[13]
                },
                "scores": {
                    "overall": float(row[1]) if row[1] else 0,
                    "price": float(row[2]) if row[2] else 0,
                    "delivery": float(row[3]) if row[3] else 0,
                    "quantity": float(row[4]) if row[4] else 0,
                    "discount": float(row[5]) if row[5] else 0
                },
                "ai_analysis": ai_analysis,  # This should now be the full rich structure
                "recommendation": row[7],
                "evaluated_at": row[8].isoformat() if row[8] else None
            }
            
        except Exception as e:
            logger.error(f"Error getting evaluation report: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def generate_rfq_ai_summary(self, rfq_id: str, ranked_bids: List[Dict]) -> Dict[str, Any]:
        """
        Generate an AI-powered summary and recommendation for all bids in an RFQ
        """
        try:
            if not ranked_bids:
                return {
                    "status": "success",
                    "summary": {
                        "top_performer": None,
                        "best_price": None,
                        "recommendation": "No bids available for analysis",
                        "detailed_analysis": "No bids were submitted for this RFQ."
                    }
                }
            
            # Prepare data for AI analysis
            top_bid = ranked_bids[0]
            lowest_price = min(ranked_bids, key=lambda x: x['amount'])
            
            # Get detailed evaluations for top bids
            detailed_evaluations = []
            for bid in ranked_bids[:3]:  # Get top 3 bids
                eval_report = self.get_evaluation_report(bid['mapping_id'])
                if eval_report.get('status') == 'success':
                    detailed_evaluations.append({
                        "supplier_name": bid['supplier_name'],
                        "score": bid['overall_score'],
                        "amount": bid['amount'],
                        "currency": bid['currency'],
                        "recommendation": bid['recommendation'],
                        "ai_analysis": eval_report.get('ai_analysis', {})
                    })
            
            # Create prompt for AI summary
            system_prompt = """You are an expert procurement analyst. Generate a comprehensive summary of all bids for this RFQ.
            Provide insights on:
            1. Overall competitive landscape
            2. Key differentiators between top bids
            3. Risk factors and opportunities
            4. Clear recommendation with justification
            
            Return your analysis as a structured JSON object."""
            
            user_prompt = f"""
            RFQ ID: {rfq_id}
            Total Bids: {len(ranked_bids)}
            
            Ranked Bids:
            {json.dumps([{
                'rank': i+1,
                'supplier': b['supplier_name'],
                'score': b['overall_score'],
                'amount': b['amount'],
                'currency': b['currency'],
                'recommendation': b['recommendation']
            } for i, b in enumerate(ranked_bids)], indent=2)}
            
            Detailed Analysis of Top Bids:
            {json.dumps(detailed_evaluations, indent=2, default=str)}
            
            Provide a comprehensive analysis with the following structure:
            {{
                "top_performer": {{
                    "supplier_name": "...",
                    "score": 0,
                    "strengths": ["..."],
                    "key_advantages": "..."
                }},
                "best_price": {{
                    "supplier_name": "...",
                    "amount": 0,
                    "currency": "...",
                    "trade_offs": "..."
                }},
                "competitive_landscape": "...",
                "risk_assessment": "...",
                "recommendation": "...",
                "recommendation_rationale": "...",
                "negotiation_strategies": ["..."],
                "next_steps": ["..."]
            }}
            """
            
            full_prompt = f"{system_prompt}\n\n{user_prompt}"
            
            if llm_service is None:
                logger.warning("LLM service not available")
                return self._get_default_rfq_summary(ranked_bids)
            
            # Invoke LLM
            response = llm_service.invoke_with_recovery(
                model_name=self.model_name,
                params=self.params,
                prompt=full_prompt,
                max_retries=1
            )
            
            # Parse the response
            try:
                summary_data = self._clean_and_parse_json(response)
            except:
                # Fallback to default summary
                summary_data = self._get_default_rfq_summary(ranked_bids)
            
            # Add trade-off analysis
            if top_bid['mapping_id'] != lowest_price['mapping_id']:
                summary_data['trade_off'] = self._generate_trade_off_analysis(top_bid, lowest_price)
            else:
                summary_data['trade_off'] = "The top-performing bid also offers the best price."
            
            return {
                "status": "success",
                "summary": summary_data
            }
            
        except Exception as e:
            logger.error(f"Error generating RFQ AI summary: {str(e)}")
            return {
                "status": "error",
                "message": str(e),
                "summary": self._get_default_rfq_summary(ranked_bids) if ranked_bids else {}
            }

    def _get_default_rfq_summary(self, ranked_bids: List[Dict]) -> Dict:
        """Generate default summary when AI fails"""
        if not ranked_bids:
            return {
                "top_performer": None,
                "best_price": None,
                "recommendation": "No bids available",
                "recommendation_rationale": "No bids were submitted for this RFQ.",
                "competitive_landscape": "No bids to analyze.",
                "risk_assessment": "N/A",
                "negotiation_strategies": [],
                "next_steps": ["Consider re-issuing the RFQ"]
            }
        
        top_bid = ranked_bids[0]
        lowest_price = min(ranked_bids, key=lambda x: x['amount'])
        
        recommendation = f"Based on the analysis, {top_bid['supplier_name']} is the recommended supplier"
        if top_bid['overall_score'] >= 80:
            recommendation += " with excellent scores across all criteria."
        elif top_bid['overall_score'] >= 60:
            recommendation += " showing solid performance, though some areas may need attention."
        else:
            recommendation += ", but all bids have significant weaknesses."
        
        return {
            "top_performer": {
                "supplier_name": top_bid['supplier_name'],
                "score": top_bid['overall_score'],
                "strengths": ["Competitive pricing", "Good delivery terms"] if top_bid['overall_score'] > 70 else ["Acceptable bid"],
                "key_advantages": f"Score of {top_bid['overall_score']}/100"
            },
            "best_price": {
                "supplier_name": lowest_price['supplier_name'],
                "amount": lowest_price['amount'],
                "currency": lowest_price['currency'],
                "trade_offs": "Lowest price but may have other considerations"
            },
            "competitive_landscape": f"Received {len(ranked_bids)} bids. Top score: {top_bid['overall_score']}, Lowest price: {lowest_price['currency']} {lowest_price['amount']:,.2f}",
            "risk_assessment": "Medium risk - standard procurement process",
            "recommendation": top_bid['recommendation'],
            "recommendation_rationale": recommendation,
            "negotiation_strategies": [
                "Negotiate volume discounts",
                "Discuss delivery timelines",
                "Review payment terms"
            ],
            "next_steps": [
                "Review top bidder's capabilities",
                "Conduct reference checks",
                "Prepare award documentation"
            ]
        }

    def _generate_trade_off_analysis(self, top_bid: Dict, lowest_price: Dict) -> str:
        """Generate trade-off analysis between top performer and lowest price"""
        
        # Get detailed evaluations
        top_eval = self.get_evaluation_report(top_bid['mapping_id'])
        price_eval = self.get_evaluation_report(lowest_price['mapping_id'])
        
        top_scores = top_eval.get('scores', {}) if top_eval.get('status') == 'success' else {}
        price_scores = price_eval.get('scores', {}) if price_eval.get('status') == 'success' else {}
        
        advantages = []
        if top_scores.get('delivery', 0) > price_scores.get('delivery', 0):
            advantages.append("better delivery terms")
        if top_scores.get('quantity', 0) > price_scores.get('quantity', 0):
            advantages.append("higher quantity fulfillment")
        if top_scores.get('discount', 0) > price_scores.get('discount', 0):
            advantages.append("better discount potential")
        
        if advantages:
            return f"The highest-scoring bid ({top_bid['supplier_name']}) is not the cheapest, but offers {' and '.join(advantages)} compared to the lowest price bid ({lowest_price['supplier_name']})."
        else:
            return f"The highest-scoring bid ({top_bid['supplier_name']}) provides better overall value despite being higher priced than {lowest_price['supplier_name']}."